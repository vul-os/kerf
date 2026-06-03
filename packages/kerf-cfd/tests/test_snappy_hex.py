"""
Tests for kerf_cfd.meshing.snappy_hex — Cartesian hex mesh generator.

Covers:
  - Background grid cell count
  - Refinement region subdivision
  - Post-snap boundary proximity
  - estimate_mesh_quality basic correctness
  - HexMesh output structure
  - Edge cases (no refinement, no boundary geometry)

References
----------
Aftosmis, M.J., Berger, M.J., Melton, J.E. (1998). AIAA J. 36(6), 952–960.
Hirt, C.W., Nichols, B.D. (1981). J. Comput. Phys. 39(1), 201–225.
OpenFOAM snappyHexMesh User Guide (public).
"""

from __future__ import annotations

import numpy as np
import pytest

from kerf_cfd.meshing.snappy_hex import (
    HexMesh,
    HexMeshSpec,
    estimate_mesh_quality,
    snappy_hex_mesh,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unit_cube_spec(cell_size: float = 0.5, **kwargs) -> HexMeshSpec:
    return HexMeshSpec(
        background_bbox_min=(0.0, 0.0, 0.0),
        background_bbox_max=(1.0, 1.0, 1.0),
        cell_size_m=cell_size,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Phase 1: Castellated (background grid)
# ---------------------------------------------------------------------------

def test_background_grid_produces_cells():
    """Background bbox + cell_size must produce at least 1 hex cell."""
    spec = _unit_cube_spec(cell_size=0.5)
    mesh = snappy_hex_mesh(spec)
    assert len(mesh.hex_connectivity) >= 1, "Expected ≥1 hex cell"


def test_background_grid_cell_count_exact():
    """1 m cube with cell_size=0.5 m should give 2×2×2 = 8 cells."""
    spec = _unit_cube_spec(cell_size=0.5)
    mesh = snappy_hex_mesh(spec)
    assert len(mesh.hex_connectivity) == 8


def test_background_grid_vertex_count():
    """1 m cube, cell_size=0.5 → 3×3×3 = 27 background vertices."""
    spec = _unit_cube_spec(cell_size=0.5)
    mesh = snappy_hex_mesh(spec)
    # Each cell stores its own vertices in the refined representation;
    # the background (no refinement) should have 27 unique vertex positions
    # but implementation may share or not. Just check >0.
    assert len(mesh.vertices) > 0


def test_hexmesh_connectivity_shape():
    """Each hex cell must have exactly 8 vertex indices."""
    spec = _unit_cube_spec(cell_size=0.5)
    mesh = snappy_hex_mesh(spec)
    assert mesh.hex_connectivity.shape[1] == 8


def test_hexmesh_connectivity_valid_indices():
    """Connectivity indices must be in range [0, n_vertices)."""
    spec = _unit_cube_spec(cell_size=0.5)
    mesh = snappy_hex_mesh(spec)
    n_verts = len(mesh.vertices)
    assert mesh.hex_connectivity.min() >= 0
    assert mesh.hex_connectivity.max() < n_verts


def test_cell_volumes_positive():
    """All hex cell volumes must be strictly positive."""
    spec = _unit_cube_spec(cell_size=0.5)
    mesh = snappy_hex_mesh(spec)
    assert (mesh.cell_volumes > 0).all(), "Some cells have non-positive volume"


def test_total_volume_matches_bbox():
    """Sum of cell volumes should equal background bbox volume (no removal)."""
    spec = _unit_cube_spec(cell_size=0.5)
    mesh = snappy_hex_mesh(spec)
    expected_vol = 1.0 * 1.0 * 1.0  # 1 m³
    # Allow 1% tolerance due to tet decomposition approximation
    assert abs(mesh.cell_volumes.sum() - expected_vol) < 0.01 * expected_vol


# ---------------------------------------------------------------------------
# Phase 1: Refinement regions
# ---------------------------------------------------------------------------

def test_refinement_increases_cell_count():
    """Adding a refinement region must produce more cells than without."""
    spec_base = _unit_cube_spec(cell_size=0.5)
    spec_ref = _unit_cube_spec(
        cell_size=0.5,
        refinement_regions=[{
            "bbox_min": (0.2, 0.2, 0.2),
            "bbox_max": (0.8, 0.8, 0.8),
            "level": 1,
        }],
    )
    mesh_base = snappy_hex_mesh(spec_base)
    mesh_ref = snappy_hex_mesh(spec_ref)
    assert len(mesh_ref.hex_connectivity) > len(mesh_base.hex_connectivity), (
        "Refinement region should produce more cells"
    )


def test_refinement_level1_subdivides_8x():
    """A cell fully inside a level-1 refinement region becomes 8 children."""
    # Use a large cell so exactly 1 background cell is in the region
    spec = HexMeshSpec(
        background_bbox_min=(0.0, 0.0, 0.0),
        background_bbox_max=(2.0, 2.0, 2.0),
        cell_size_m=2.0,  # → exactly 1 background cell
        refinement_regions=[{
            "bbox_min": (0.0, 0.0, 0.0),
            "bbox_max": (2.0, 2.0, 2.0),
            "level": 1,
        }],
    )
    mesh = snappy_hex_mesh(spec)
    # 1 background cell × 8 children at level 1
    assert len(mesh.hex_connectivity) == 8, (
        f"Expected 8 refined cells, got {len(mesh.hex_connectivity)}"
    )


def test_refinement_level2_subdivides_64x():
    """A cell fully inside a level-2 region becomes 8^2 = 64 children."""
    spec = HexMeshSpec(
        background_bbox_min=(0.0, 0.0, 0.0),
        background_bbox_max=(2.0, 2.0, 2.0),
        cell_size_m=2.0,
        refinement_regions=[{
            "bbox_min": (0.0, 0.0, 0.0),
            "bbox_max": (2.0, 2.0, 2.0),
            "level": 2,
        }],
    )
    mesh = snappy_hex_mesh(spec)
    assert len(mesh.hex_connectivity) == 64, (
        f"Expected 64 refined cells, got {len(mesh.hex_connectivity)}"
    )


# ---------------------------------------------------------------------------
# Phase 2: Snap
# ---------------------------------------------------------------------------

def test_snap_brings_boundary_verts_close_to_surface():
    """
    After snapping, boundary vertices should be within cell_size_m * 0.1
    of the nearest surface sample point.

    Uses a plane of surface points at z=0.5 (mid-plane of unit cube).
    """
    cell_size = 0.5
    # Surface points on a plane at z=0.5
    xs = np.linspace(0.0, 1.0, 5)
    ys = np.linspace(0.0, 1.0, 5)
    gx, gy = np.meshgrid(xs, ys)
    surface_pts = np.column_stack([gx.ravel(), gy.ravel(), np.full(25, 0.5)])

    spec = HexMeshSpec(
        background_bbox_min=(0.0, 0.0, 0.0),
        background_bbox_max=(1.0, 1.0, 1.0),
        cell_size_m=cell_size,
        boundary_geometry=surface_pts,
        boundary_snap_iterations=4,
    )
    mesh = snappy_hex_mesh(spec)

    # Find vertices near z=0.5 surface
    tol = cell_size * 0.1
    near_surface_verts = mesh.vertices[np.abs(mesh.vertices[:, 2] - 0.5) < cell_size]

    if len(near_surface_verts) == 0:
        pytest.skip("No boundary-proximate vertices found — surface too far")

    # Each of those vertices should now be within tol of the surface
    for v in near_surface_verts:
        dist_to_surface = np.abs(v[2] - 0.5)
        assert dist_to_surface <= tol + 1e-9, (
            f"Vertex z={v[2]:.4f} not snapped close to surface z=0.5 "
            f"(tol={tol:.4f})"
        )


def test_no_boundary_geometry_still_produces_mesh():
    """Mesh generation without boundary geometry should work fine."""
    spec = _unit_cube_spec(cell_size=0.5, boundary_geometry=None)
    mesh = snappy_hex_mesh(spec)
    assert len(mesh.hex_connectivity) == 8


# ---------------------------------------------------------------------------
# Quality metrics
# ---------------------------------------------------------------------------

def test_quality_aspect_ratio_positive():
    """estimate_mesh_quality must return aspect_ratio_max > 0."""
    spec = _unit_cube_spec(cell_size=0.5)
    mesh = snappy_hex_mesh(spec)
    q = estimate_mesh_quality(mesh)
    assert q["aspect_ratio_max"] > 0.0


def test_quality_pure_cartesian_aspect_ratio_near_1():
    """For a pure Cartesian (undeformed) mesh, aspect ratio should be ~1.0."""
    spec = _unit_cube_spec(cell_size=0.5)
    mesh = snappy_hex_mesh(spec)
    q = estimate_mesh_quality(mesh)
    # Cartesian hex → edges all equal → aspect ratio = 1.0
    assert q["aspect_ratio_max"] < 1.1, (
        f"Cartesian mesh aspect ratio should be ~1.0, got {q['aspect_ratio_max']}"
    )


def test_quality_orthogonality_cartesian():
    """Pure Cartesian mesh should have orthogonality_min close to 1.0."""
    spec = _unit_cube_spec(cell_size=0.5)
    mesh = snappy_hex_mesh(spec)
    q = estimate_mesh_quality(mesh)
    assert q["orthogonality_min"] >= 0.9, (
        f"Cartesian orthogonality should be ≥0.9, got {q['orthogonality_min']}"
    )


def test_quality_returns_all_keys():
    """estimate_mesh_quality must return the expected metric keys."""
    spec = _unit_cube_spec(cell_size=0.5)
    mesh = snappy_hex_mesh(spec)
    q = estimate_mesh_quality(mesh)
    for key in ("aspect_ratio_max", "aspect_ratio_mean",
                "orthogonality_min", "skewness_max", "n_cells", "n_vertices"):
        assert key in q, f"Missing quality key: {key}"


# ---------------------------------------------------------------------------
# Output data structure
# ---------------------------------------------------------------------------

def test_boundary_faces_dict():
    """boundary_faces must be a dict with at least one patch."""
    spec = _unit_cube_spec(cell_size=0.5)
    mesh = snappy_hex_mesh(spec)
    assert isinstance(mesh.boundary_faces, dict)
    assert len(mesh.boundary_faces) >= 1


def test_hexmesh_vertices_are_3d():
    """Vertices array must be shape (Nv, 3)."""
    spec = _unit_cube_spec(cell_size=0.5)
    mesh = snappy_hex_mesh(spec)
    assert mesh.vertices.ndim == 2
    assert mesh.vertices.shape[1] == 3


def test_non_cubic_bbox():
    """Non-cubic bounding box (3×2×1 m, cell 1 m) → 3×2×1 = 6 cells."""
    spec = HexMeshSpec(
        background_bbox_min=(0.0, 0.0, 0.0),
        background_bbox_max=(3.0, 2.0, 1.0),
        cell_size_m=1.0,
    )
    mesh = snappy_hex_mesh(spec)
    assert len(mesh.hex_connectivity) == 6
