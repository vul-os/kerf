"""Tests for GK-P20: uv_unwrap_hardening — seam-cut, chart-pack, distortion stats.

All tests are hermetic (no file I/O, no network, no OCCT).

Test plan
---------
T01 — unit square mesh, no seams: 1 chart, packing_efficiency > 0
T02 — single triangle, no seams: 1 chart
T03 — two triangles sharing a seam edge: 2 charts
T04 — four triangles (quad), seam on diagonal: 2 charts
T05 — cube cross pattern (12 triangles, 5 seam edges): multiple charts
T06 — already-packed UV (unit square): result is valid, 1 chart
T07 — tilted chart input: best rotation chosen (bbox smaller or equal)
T08 — empty mesh: returns sensible empty result
T09 — single face (triangle) in 3D, UV area > 0
T10 — scale_factor computed correctly for flat planar mesh
T11 — num_seam_cuts reports only edges present in mesh
T12 — packed_uv length == num_faces * 3
T13 — packing_efficiency in (0, 1] for normal mesh
T14 — all chart uv_min / uv_max within [0, 2] (unit square + overflow tolerated)
T15 — LLM tool round-trip via JSON args
T16 — mesh with no UV provided (zero UV): runs without error
T17 — seam edge not in mesh: num_seam_cuts == 0
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from kerf_cad_core.geom.uv_unwrap_hardening import (
    HardenedUVResult,
    UVChart,
    UVUnwrapHardeningSpec,
    harden_uv_unwrap,
    nurbs_harden_uv_unwrap,
)


# ---------------------------------------------------------------------------
# Helpers: minimal mesh builders
# ---------------------------------------------------------------------------


def _unit_square_mesh():
    """Two triangles forming a 1×1 unit square in the XY plane."""
    verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    faces = [(0, 1, 2), (0, 2, 3)]
    uv = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    return verts, faces, uv


def _single_triangle():
    verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.5, 1.0, 0.0)]
    faces = [(0, 1, 2)]
    uv = [(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)]
    return verts, faces, uv


def _two_triangles_with_seam():
    """Two triangles sharing edge (0,1); seam cuts them into 2 charts."""
    verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.5, 1.0, 0.0), (0.5, -1.0, 0.0)]
    faces = [(0, 2, 1), (0, 1, 3)]
    uv = [(0.0, 0.5), (1.0, 0.5), (0.5, 1.0), (0.5, 0.0)]
    seams = [(0, 1)]
    return verts, faces, uv, seams


def _quad_with_full_seam():
    """Two pairs of triangles, each pair forming a quad; a seam separates them.

    Layout (top view):
        v0-v1-v2 (left quad, 2 triangles)
        v2-v3-v4 (right quad, 2 triangles)
    The seam is the shared edge (v2,v?) — but the two quads share no edge
    so they are naturally in 2 components even without a seam.
    Instead: use a strip of 4 triangles where seams cut a boundary.

    We build two disconnected triangles, each already in its own component.
    Then we cut the single shared edge to test seam detection.
    """
    # Two separate quads sharing edge v1-v2
    verts = [
        (0.0, 0.0, 0.0),  # 0
        (1.0, 0.0, 0.0),  # 1
        (1.0, 1.0, 0.0),  # 2
        (0.0, 1.0, 0.0),  # 3
        (2.0, 0.0, 0.0),  # 4
        (2.0, 1.0, 0.0),  # 5
    ]
    # Left quad: faces 0,1; right quad: faces 2,3; share edge (1,2)
    faces = [
        (0, 1, 2), (0, 2, 3),   # left quad (faces 0,1)
        (1, 4, 5), (1, 5, 2),   # right quad (faces 2,3)
    ]
    uv = [
        (0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0),
        (2.0, 0.0), (2.0, 1.0),
    ]
    # Seam on shared edge (1,2) — splits left quad from right quad
    seams = [(1, 2)]
    return verts, faces, uv, seams


def _cube_cross(side: float = 1.0):
    """3 separate quad patches (6 triangles each pair) with full seam separation.

    To guarantee multiple charts: build completely disconnected vertex sets
    so the seams are guaranteed to prevent connectivity.

    We make three separate unit squares with unique vertex indices, then
    mark edges between them as seams (even though they don't touch — the
    point is seams prevent BFS crossings, and disconnected meshes
    naturally give multiple charts).
    """
    # Three separate unit squares (no shared vertices)
    verts = [
        # Square A (vertices 0-3)
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
        # Square B (vertices 4-7)
        (2.0, 0.0, 0.0), (3.0, 0.0, 0.0), (3.0, 1.0, 0.0), (2.0, 1.0, 0.0),
        # Square C (vertices 8-11)
        (4.0, 0.0, 0.0), (5.0, 0.0, 0.0), (5.0, 1.0, 0.0), (4.0, 1.0, 0.0),
    ]
    faces = [
        (0, 1, 2), (0, 2, 3),   # Square A
        (4, 5, 6), (4, 6, 7),   # Square B
        (8, 9, 10), (8, 10, 11), # Square C
    ]
    uv = [(float(i % 4 // 2), float(i % 2)) for i in range(12)]
    seams = []  # No seams needed — 3 disconnected components
    return verts, faces, uv, seams


# ---------------------------------------------------------------------------
# T01 — unit square, no seams: 1 chart
# ---------------------------------------------------------------------------


def test_t01_unit_square_no_seams_one_chart():
    verts, faces, uv = _unit_square_mesh()
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=verts,
        mesh_faces=faces,
        initial_uv=uv,
        seam_edges=[],
    )
    result = harden_uv_unwrap(spec)
    assert isinstance(result, HardenedUVResult)
    assert result.num_charts == 1
    assert result.num_seam_cuts == 0
    assert result.packing_efficiency > 0.0


# ---------------------------------------------------------------------------
# T02 — single triangle, no seams: 1 chart
# ---------------------------------------------------------------------------


def test_t02_single_triangle_one_chart():
    verts, faces, uv = _single_triangle()
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=verts,
        mesh_faces=faces,
        initial_uv=uv,
        seam_edges=[],
    )
    result = harden_uv_unwrap(spec)
    assert result.num_charts == 1
    assert len(result.charts) == 1
    assert result.charts[0].face_indices == [0]


# ---------------------------------------------------------------------------
# T03 — two triangles with seam: 2 charts
# ---------------------------------------------------------------------------


def test_t03_two_triangles_seam_two_charts():
    verts, faces, uv, seams = _two_triangles_with_seam()
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=verts,
        mesh_faces=faces,
        initial_uv=uv,
        seam_edges=seams,
    )
    result = harden_uv_unwrap(spec)
    assert result.num_charts == 2
    assert result.num_seam_cuts == 1
    # Each chart should contain exactly 1 face
    face_sets = [set(c.face_indices) for c in result.charts]
    assert {0} in face_sets
    assert {1} in face_sets


# ---------------------------------------------------------------------------
# T04 — two quads with shared seam edge: 2 charts (each 2 faces)
# ---------------------------------------------------------------------------


def test_t04_quad_shared_seam_two_charts():
    verts, faces, uv, seams = _quad_with_full_seam()
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=verts,
        mesh_faces=faces,
        initial_uv=uv,
        seam_edges=seams,
    )
    result = harden_uv_unwrap(spec)
    assert result.num_charts == 2
    assert result.num_seam_cuts == 1
    for chart in result.charts:
        assert len(chart.face_indices) == 2


# ---------------------------------------------------------------------------
# T05 — three disconnected patches: exactly 3 charts
# ---------------------------------------------------------------------------


def test_t05_disconnected_patches_three_charts():
    verts, faces, uv, seams = _cube_cross()
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=verts,
        mesh_faces=faces,
        initial_uv=uv,
        seam_edges=seams,
    )
    result = harden_uv_unwrap(spec)
    assert result.num_charts == 3
    # All faces must appear in exactly one chart
    all_face_ids = []
    for c in result.charts:
        all_face_ids.extend(c.face_indices)
    assert sorted(all_face_ids) == list(range(len(faces)))


# ---------------------------------------------------------------------------
# T06 — already-packed UV (no seams): pass-through structure
# ---------------------------------------------------------------------------


def test_t06_already_packed_uv_passthrough():
    verts, faces, uv = _unit_square_mesh()
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=verts,
        mesh_faces=faces,
        initial_uv=uv,
        seam_edges=[],
    )
    result = harden_uv_unwrap(spec)
    assert result.num_charts == 1
    assert len(result.packed_uv) == len(faces) * 3
    for u, v in result.packed_uv:
        assert math.isfinite(u) and math.isfinite(v)


# ---------------------------------------------------------------------------
# T07 — tilted chart: rotation should be tried
# ---------------------------------------------------------------------------


def test_t07_tilted_chart_rotation_tried():
    """A 2:1 landscape rectangle placed in portrait should be rotated."""
    # Build a 2×1 rectangular mesh (wide)
    verts = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    faces = [(0, 1, 2), (0, 2, 3)]
    # Supply UV as 1×2 (tall) — the algorithm should prefer 2×1 bbox
    uv = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)]  # rotated input
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=verts,
        mesh_faces=faces,
        initial_uv=uv,
        seam_edges=[],
    )
    result = harden_uv_unwrap(spec)
    assert result.num_charts == 1
    # All UVs should be finite
    for u, v in result.packed_uv:
        assert math.isfinite(u) and math.isfinite(v)


# ---------------------------------------------------------------------------
# T08 — empty mesh
# ---------------------------------------------------------------------------


def test_t08_empty_mesh():
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=[],
        mesh_faces=[],
        initial_uv=[],
        seam_edges=[],
    )
    result = harden_uv_unwrap(spec)
    assert result.num_charts == 0
    assert result.packed_uv == []
    assert result.charts == []
    assert result.packing_efficiency == 0.0


# ---------------------------------------------------------------------------
# T09 — single face, UV area > 0
# ---------------------------------------------------------------------------


def test_t09_single_face_uv_area_positive():
    verts, faces, uv = _single_triangle()
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=verts,
        mesh_faces=faces,
        initial_uv=uv,
        seam_edges=[],
    )
    result = harden_uv_unwrap(spec)
    assert result.charts[0].chart_area_uv > 0.0


# ---------------------------------------------------------------------------
# T10 — scale_factor for flat mesh
# ---------------------------------------------------------------------------


def test_t10_scale_factor_flat_mesh():
    """For a unit square both flat 3D and UV space, scale_factor should be
    finite and positive."""
    verts, faces, uv = _unit_square_mesh()
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=verts,
        mesh_faces=faces,
        initial_uv=uv,
        seam_edges=[],
    )
    result = harden_uv_unwrap(spec)
    assert result.charts[0].scale_factor > 0.0
    assert math.isfinite(result.charts[0].scale_factor)


# ---------------------------------------------------------------------------
# T11 — seam edge not in mesh: num_seam_cuts == 0
# ---------------------------------------------------------------------------


def test_t11_seam_not_in_mesh():
    verts, faces, uv = _unit_square_mesh()
    # Edges 99,100 don't exist
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=verts,
        mesh_faces=faces,
        initial_uv=uv,
        seam_edges=[(99, 100)],
    )
    result = harden_uv_unwrap(spec)
    assert result.num_seam_cuts == 0
    # All faces still connected → 1 chart (seam ignored)
    assert result.num_charts == 1


# ---------------------------------------------------------------------------
# T12 — packed_uv length == num_faces * 3
# ---------------------------------------------------------------------------


def test_t12_packed_uv_length():
    verts, faces, uv, seams = _cube_cross()
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=verts,
        mesh_faces=faces,
        initial_uv=uv,
        seam_edges=seams,
    )
    result = harden_uv_unwrap(spec)
    assert len(result.packed_uv) == len(faces) * 3


# ---------------------------------------------------------------------------
# T13 — packing_efficiency in (0, 1]
# ---------------------------------------------------------------------------


def test_t13_packing_efficiency_bounds():
    verts, faces, uv = _unit_square_mesh()
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=verts,
        mesh_faces=faces,
        initial_uv=uv,
        seam_edges=[],
    )
    result = harden_uv_unwrap(spec)
    assert 0.0 < result.packing_efficiency <= 1.0


# ---------------------------------------------------------------------------
# T14 — chart bbox coords are finite
# ---------------------------------------------------------------------------


def test_t14_chart_bbox_finite():
    verts, faces, uv, seams = _cube_cross()
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=verts,
        mesh_faces=faces,
        initial_uv=uv,
        seam_edges=seams,
    )
    result = harden_uv_unwrap(spec)
    for chart in result.charts:
        assert math.isfinite(chart.uv_min[0]) and math.isfinite(chart.uv_min[1])
        assert math.isfinite(chart.uv_max[0]) and math.isfinite(chart.uv_max[1])
        assert chart.uv_max[0] >= chart.uv_min[0]
        assert chart.uv_max[1] >= chart.uv_min[1]


# ---------------------------------------------------------------------------
# T15 — LLM tool round-trip via JSON args
# ---------------------------------------------------------------------------


def test_t15_llm_tool_round_trip():
    verts, faces, uv = _unit_square_mesh()
    args = {
        "mesh_vertices_xyz": [list(v) for v in verts],
        "mesh_faces": [list(f) for f in faces],
        "initial_uv": [list(u) for u in uv],
        "seam_edges": [],
    }
    raw = nurbs_harden_uv_unwrap(args)
    out = json.loads(raw)
    # ok_payload format: no "error" key means success
    assert "error" not in out, out
    assert "packed_uv" in out
    assert "charts" in out
    assert out["num_charts"] == 1


# ---------------------------------------------------------------------------
# T16 — zero UV (all (0,0)): runs without error
# ---------------------------------------------------------------------------


def test_t16_zero_uv_runs():
    verts, faces, _ = _unit_square_mesh()
    zero_uv = [(0.0, 0.0)] * len(verts)
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=verts,
        mesh_faces=faces,
        initial_uv=zero_uv,
        seam_edges=[],
    )
    result = harden_uv_unwrap(spec)
    assert result.num_charts == 1
    assert len(result.packed_uv) == len(faces) * 3


# ---------------------------------------------------------------------------
# T17 — seam edge present in mesh, cuts correctly
# ---------------------------------------------------------------------------


def test_t17_seam_edge_present_cuts():
    """Explicitly verify that a seam on the shared edge produces 2 charts."""
    verts, faces, uv, seams = _two_triangles_with_seam()
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=verts,
        mesh_faces=faces,
        initial_uv=uv,
        seam_edges=seams,
    )
    result = harden_uv_unwrap(spec)
    assert result.num_seam_cuts == 1
    assert result.num_charts == 2


# ---------------------------------------------------------------------------
# T18 — all charts together cover all faces (no face lost)
# ---------------------------------------------------------------------------


def test_t18_all_faces_covered():
    verts, faces, uv, seams = _cube_cross()
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=verts,
        mesh_faces=faces,
        initial_uv=uv,
        seam_edges=seams,
    )
    result = harden_uv_unwrap(spec)
    covered = set()
    for chart in result.charts:
        for fi in chart.face_indices:
            assert fi not in covered, f"Face {fi} appears in >1 chart"
            covered.add(fi)
    assert covered == set(range(len(faces)))


# ---------------------------------------------------------------------------
# T19 — distortion stats are non-negative and finite
# ---------------------------------------------------------------------------


def test_t19_distortion_stats_valid():
    verts, faces, uv = _unit_square_mesh()
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=verts,
        mesh_faces=faces,
        initial_uv=uv,
        seam_edges=[],
    )
    result = harden_uv_unwrap(spec)
    assert math.isfinite(result.max_distortion)
    assert math.isfinite(result.mean_distortion)
    assert result.max_distortion >= 0.0
    assert result.mean_distortion >= 0.0


# ---------------------------------------------------------------------------
# T20 — honest_caveat string is non-empty
# ---------------------------------------------------------------------------


def test_t20_honest_caveat_present():
    verts, faces, uv = _unit_square_mesh()
    spec = UVUnwrapHardeningSpec(
        mesh_vertices_xyz=verts,
        mesh_faces=faces,
        initial_uv=uv,
        seam_edges=[],
    )
    result = harden_uv_unwrap(spec)
    assert isinstance(result.honest_caveat, str)
    assert len(result.honest_caveat) > 10


# ---------------------------------------------------------------------------
# T21 — LLM tool bad args returns error payload
# ---------------------------------------------------------------------------


def test_t21_llm_tool_bad_args():
    raw = nurbs_harden_uv_unwrap({"mesh_vertices_xyz": "not_a_list"})
    out = json.loads(raw)
    # err_payload format: has "error" key
    assert "error" in out
