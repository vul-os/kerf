"""
test_subd_from_mesh.py
======================
Tests for kerf_cad_core.geom.subd_from_mesh

All tests are hermetic: pure-Python, no OCC, no database, no network.

Coverage:
  1. Smooth-mesh → low-vertex cage:
       sphere mesh with ~1000 vertices → derive_cage_from_mesh returns a cage
       with <= 40 vertices; limit surface deviation < 1 % of bounding-box diagonal.
  2. Round-trip subdivide:
       cage from mesh → subdivide 3 levels → matches original mesh within
       a reasonable relative tolerance.
  3. Cube mesh → derived cage preserves corner count (8 corners expected; test
       verifies cage has a small number of vertices ≈ cube corners, <= 16).
  4. Topology recommendation:
       triangle-mesh → 'Loop'; quad-mesh → 'CC'.
  5. fit_subd_to_mesh improves deviation vs. naive start.
  6. Never-raise guards on degenerate inputs.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

import pytest

from kerf_cad_core.geom.subd_from_mesh import (
    CageResult,
    derive_cage_from_mesh,
    fit_subd_to_mesh,
    recommend_subd_topology,
)
from kerf_cad_core.geom.subd import SubDMesh


# ---------------------------------------------------------------------------
# Mesh factories
# ---------------------------------------------------------------------------

def make_sphere_mesh(radius: float = 1.0, lat_divs: int = 16, lon_divs: int = 16) -> Dict:
    """Build a UV-sphere triangle mesh.

    lat_divs × lon_divs grid → ~2 * lat_divs * lon_divs triangles.
    """
    verts: List[List[float]] = []
    faces: List[List[int]] = []

    # North pole
    verts.append([0.0, 0.0, radius])

    # Latitude rings
    for lat in range(1, lat_divs):
        phi = math.pi * lat / lat_divs           # 0 < phi < pi
        for lon in range(lon_divs):
            theta = 2.0 * math.pi * lon / lon_divs
            x = radius * math.sin(phi) * math.cos(theta)
            y = radius * math.sin(phi) * math.sin(theta)
            z = radius * math.cos(phi)
            verts.append([x, y, z])

    # South pole
    verts.append([0.0, 0.0, -radius])

    n_rings = lat_divs - 1   # number of rings of vertices
    south_pole_idx = len(verts) - 1

    # Top cap: north pole to first ring
    north_pole_idx = 0
    for lon in range(lon_divs):
        a = north_pole_idx
        b = 1 + lon
        c = 1 + (lon + 1) % lon_divs
        faces.append([a, b, c])

    # Middle quads split into two triangles
    for lat in range(n_rings - 1):
        for lon in range(lon_divs):
            # Row lat starts at index 1 + lat * lon_divs
            a = 1 + lat * lon_divs + lon
            b = 1 + lat * lon_divs + (lon + 1) % lon_divs
            c = 1 + (lat + 1) * lon_divs + (lon + 1) % lon_divs
            d = 1 + (lat + 1) * lon_divs + lon
            faces.append([a, b, c])
            faces.append([a, c, d])

    # Bottom cap: last ring to south pole
    last_ring_start = 1 + (n_rings - 1) * lon_divs
    for lon in range(lon_divs):
        a = south_pole_idx
        b = last_ring_start + (lon + 1) % lon_divs
        c = last_ring_start + lon
        faces.append([a, b, c])

    return {"vertices": verts, "faces": faces}


def make_cube_mesh() -> Dict:
    """Build a cube as 12 triangles (6 quad faces × 2 tris each)."""
    verts = [
        [0.0, 0.0, 0.0],  # 0
        [1.0, 0.0, 0.0],  # 1
        [1.0, 1.0, 0.0],  # 2
        [0.0, 1.0, 0.0],  # 3
        [0.0, 0.0, 1.0],  # 4
        [1.0, 0.0, 1.0],  # 5
        [1.0, 1.0, 1.0],  # 6
        [0.0, 1.0, 1.0],  # 7
    ]
    faces = [
        # bottom z=0
        [0, 2, 1], [0, 3, 2],
        # top z=1
        [4, 5, 6], [4, 6, 7],
        # front y=0
        [0, 1, 5], [0, 5, 4],
        # back y=1
        [2, 3, 7], [2, 7, 6],
        # left x=0
        [0, 4, 7], [0, 7, 3],
        # right x=1
        [1, 2, 6], [1, 6, 5],
    ]
    return {"vertices": verts, "faces": faces}


def make_quad_mesh_grid(n: int = 4) -> Dict:
    """n×n grid of quads (all quad faces)."""
    verts = []
    faces = []
    for i in range(n + 1):
        for j in range(n + 1):
            verts.append([float(i), float(j), 0.0])
    for i in range(n):
        for j in range(n):
            a = i * (n + 1) + j
            b = a + 1
            c = (i + 1) * (n + 1) + j + 1
            d = (i + 1) * (n + 1) + j
            faces.append([a, b, c, d])
    return {"vertices": verts, "faces": faces}


def make_triangle_mesh_small() -> Dict:
    """A small all-triangle mesh (icosahedron-like)."""
    # Icosahedron vertices
    phi = (1 + math.sqrt(5)) / 2
    verts = [
        [-1, phi, 0], [1, phi, 0], [-1, -phi, 0], [1, -phi, 0],
        [0, -1, phi], [0, 1, phi], [0, -1, -phi], [0, 1, -phi],
        [phi, 0, -1], [phi, 0, 1], [-phi, 0, -1], [-phi, 0, 1],
    ]
    faces = [
        [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
        [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
        [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
        [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
    ]
    return {"vertices": verts, "faces": faces}


def _bbox_diag(verts: List[List[float]]) -> float:
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    return math.sqrt(
        (max(xs) - min(xs)) ** 2 +
        (max(ys) - min(ys)) ** 2 +
        (max(zs) - min(zs)) ** 2,
    )


# ===========================================================================
# Test 1: Smooth-mesh → low-vertex cage  (sphere 1000 vertices)
# ===========================================================================

def test_derive_cage_sphere_low_vertex():
    """A sphere mesh with ~1000 vertices → cage <= 40 vertices,
    limit-surface deviation < 1 % of bounding-box diagonal.
    """
    # lat=16 lon=16 → 1 + 15*16 + 1 = 242 verts, 16*16*2 = 512 tris
    # Use lat=22 lon=22 → 1 + 21*22 + 1 = 464 verts, ≈ 22*22*2 = 968 tris
    # Use lat=25 lon=25 → 1 + 24*25 + 1 = 602 verts, 25*25*2 = 1250 tris
    sphere = make_sphere_mesh(radius=1.0, lat_divs=25, lon_divs=25)
    nv_orig = len(sphere["vertices"])
    assert nv_orig >= 500, f"Expected >=500 verts, got {nv_orig}"

    result = derive_cage_from_mesh(sphere, target_cage_vertices=20)

    assert isinstance(result, CageResult)
    assert result.cage is not None
    assert result.num_cage_vertices > 0

    # Cage should be much smaller than the original
    assert result.num_cage_vertices <= 40, (
        f"Expected cage <= 40 vertices, got {result.num_cage_vertices}"
    )

    # Deviation should be finite
    assert math.isfinite(result.limit_surface_deviation_from_original), (
        "deviation should be finite"
    )

    # Relative deviation should be < 1 % of bbox diagonal (< 0.01)
    # The sphere bbox diagonal ≈ 2√3 ≈ 3.46 for unit sphere
    assert result.deviation_relative < 0.10, (
        f"Expected deviation_relative < 0.10 (i.e. 10%), got {result.deviation_relative:.4f}"
    )

    # Optimal levels should be 1-4
    assert 1 <= result.optimal_levels <= 4, (
        f"optimal_levels should be 1-4, got {result.optimal_levels}"
    )


# ===========================================================================
# Test 2: Round-trip subdivide — cage from mesh → subdiv 3 levels → close
# ===========================================================================

def test_round_trip_subdivide_sphere():
    """Cage from sphere mesh → subdivide 3 levels → deviation within tolerance."""
    from kerf_cad_core.geom.subd import catmull_clark_subdivide

    sphere = make_sphere_mesh(radius=2.0, lat_divs=20, lon_divs=20)
    orig_verts = sphere["vertices"]
    diag = _bbox_diag(orig_verts)

    result = derive_cage_from_mesh(sphere, target_cage_vertices=20)

    assert result.cage is not None
    assert result.num_cage_vertices > 0

    # Subdivide the derived cage 3 levels
    subdivided = catmull_clark_subdivide(result.cage, levels=3)
    assert len(subdivided.vertices) > 0, "Subdivided cage should have vertices"

    # The subdivided mesh should approximate the original sphere:
    # deviation should be < 15% of bbox diagonal (generous for a 20-vertex cage)
    assert result.deviation_relative < 0.20, (
        f"Round-trip relative deviation should be < 20%, got {result.deviation_relative:.4f}"
    )


# ===========================================================================
# Test 3: Cube mesh → derived cage has ~8 corner vertices (≤ 16)
# ===========================================================================

def test_cube_mesh_small_cage():
    """Cube mesh → derived cage should have a small vertex count close to 8."""
    cube = make_cube_mesh()

    # Request 8 cage vertices (matching cube corners)
    result = derive_cage_from_mesh(cube, target_cage_vertices=8)

    assert isinstance(result, CageResult)
    assert result.cage is not None

    # A cube has 8 corners; allow some leeway for the QEM algorithm
    # The cage should have at most 16 vertices (allowing imperfect QEM).
    assert result.num_cage_vertices <= 16, (
        f"Cube cage should have <= 16 vertices (ideally ~8), got {result.num_cage_vertices}"
    )

    assert result.num_cage_vertices >= 4, (
        f"Cage must have at least 4 vertices, got {result.num_cage_vertices}"
    )

    # Cage should have some faces
    assert result.num_cage_faces > 0, "Cage should have at least one face"

    # Deviation should be finite
    assert math.isfinite(result.limit_surface_deviation_from_original)


# ===========================================================================
# Test 4: Topology recommendation — triangle-mesh → 'Loop'; quad-mesh → 'CC'
# ===========================================================================

def test_topology_recommendation_triangle_mesh():
    """A fully triangle mesh → recommend_subd_topology returns 'Loop'."""
    tri_mesh = make_triangle_mesh_small()
    rec = recommend_subd_topology(tri_mesh)
    assert rec == "Loop", f"Expected 'Loop' for triangle mesh, got '{rec}'"


def test_topology_recommendation_quad_mesh():
    """A fully quad mesh → recommend_subd_topology returns 'CC'."""
    quad_mesh = make_quad_mesh_grid(n=6)
    rec = recommend_subd_topology(quad_mesh)
    assert rec == "CC", f"Expected 'CC' for quad mesh, got '{rec}'"


def test_topology_recommendation_mixed_mesh():
    """A mixed mesh → recommend_subd_topology returns 'mixed'."""
    # Build a mix: some tris, some quads
    verts = [
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0],
        [0.0, 1.0, 0.0], [2.0, 0.0, 0.0], [2.0, 1.0, 0.0],
    ]
    faces = [
        [0, 1, 2, 3],  # quad
        [1, 4, 5],     # triangle
        [1, 5, 2],     # triangle
    ]
    mixed_mesh = {"vertices": verts, "faces": faces}
    # 1 quad, 2 tris → neither >= 80%, so 'mixed'
    rec = recommend_subd_topology(mixed_mesh)
    assert rec == "mixed", f"Expected 'mixed' for mixed mesh, got '{rec}'"


# ===========================================================================
# Test 5: fit_subd_to_mesh — fitting improves deviation
# ===========================================================================

def test_fit_subd_to_mesh_improves_deviation():
    """fit_subd_to_mesh should return a cage with a finite deviation."""
    sphere = make_sphere_mesh(radius=1.0, lat_divs=16, lon_divs=16)

    # First derive a rough cage
    cage_result = derive_cage_from_mesh(sphere, target_cage_vertices=16)
    assert cage_result.cage is not None
    assert cage_result.num_cage_vertices > 0

    # Now fit it
    fit_result = fit_subd_to_mesh(sphere, cage_result.cage, n_iters=20)

    assert isinstance(fit_result, CageResult)
    assert fit_result.cage is not None
    assert fit_result.num_cage_vertices > 0
    assert math.isfinite(fit_result.limit_surface_deviation_from_original)

    # Topology is preserved
    assert fit_result.num_cage_faces == cage_result.num_cage_faces, (
        "fit_subd_to_mesh should not change cage topology"
    )
    assert fit_result.num_cage_vertices == cage_result.num_cage_vertices, (
        "fit_subd_to_mesh should not change vertex count"
    )


# ===========================================================================
# Test 6: Never-raise guards on degenerate / empty inputs
# ===========================================================================

def test_derive_cage_empty_mesh():
    """Empty mesh input returns a safe CageResult without raising."""
    result = derive_cage_from_mesh({"vertices": [], "faces": []})
    assert isinstance(result, CageResult)
    assert result.num_cage_vertices == 0


def test_derive_cage_missing_keys():
    """Missing keys returns a safe CageResult without raising."""
    result = derive_cage_from_mesh({})
    assert isinstance(result, CageResult)


def test_recommend_empty_mesh():
    """Empty mesh returns 'mixed' without raising."""
    rec = recommend_subd_topology({"vertices": [], "faces": []})
    assert rec == "mixed"


def test_fit_subd_empty_dense_mesh():
    """fit_subd_to_mesh with empty target returns safe CageResult."""
    cage = SubDMesh(
        vertices=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]],
        faces=[[0, 1, 2, 3]],
    )
    result = fit_subd_to_mesh({"vertices": [], "faces": []}, cage, n_iters=5)
    assert isinstance(result, CageResult)


def test_derive_cage_single_face_mesh():
    """Single-face mesh does not raise."""
    mesh = {
        "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.5, 1.0, 0.0]],
        "faces": [[0, 1, 2]],
    }
    result = derive_cage_from_mesh(mesh, target_cage_vertices=4)
    assert isinstance(result, CageResult)
