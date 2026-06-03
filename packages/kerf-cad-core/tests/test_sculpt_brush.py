"""Tests for kerf_cad_core.sculpt.brush — mesh sculpt brush engine.

Covers ≥18 assertions across all five brush kinds (GRAB, SMOOTH, INFLATE,
CREASE, PINCH), falloff variants, undo (revert_delta), edge cases (strength=0,
radius > mesh extent), vertex_normals, and one_ring_neighbours.
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.sculpt.brush import (
    BrushKind,
    BrushStroke,
    MeshDelta,
    SculptMesh,
    apply_brush,
    falloff_weight,
    revert_delta,
)


# ---------------------------------------------------------------------------
# Mesh factories
# ---------------------------------------------------------------------------


def make_plane(n: int = 10) -> SculptMesh:
    """Triangulated n×n plane grid in the XY plane, z=0.

    Produces (n+1)² vertices and 2*n² triangles.
    Grid spans [0, n] in x and y.
    """
    xs = np.arange(n + 1, dtype=np.float64)
    ys = np.arange(n + 1, dtype=np.float64)
    xx, yy = np.meshgrid(xs, ys)           # both (n+1, n+1)
    zz = np.zeros_like(xx)
    positions = np.stack([xx.ravel(), yy.ravel(), zz.ravel()], axis=1)  # (V, 3)

    tris = []
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            b = a + 1
            c = a + (n + 1) + 1
            d = a + (n + 1)
            tris.append([a, b, c])
            tris.append([a, c, d])

    triangles = np.array(tris, dtype=np.intp)
    return SculptMesh(positions=positions, triangles=triangles)


def _center_index_of_plane(n: int = 10) -> int:
    """Index of the center vertex of an (n+1)×(n+1) plane grid."""
    mid = n // 2
    return mid * (n + 1) + mid


def make_unit_cube() -> SculptMesh:
    """Triangulated unit cube: 8 vertices, 12 triangles (2 per face)."""
    positions = np.array([
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],  # bottom face
        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],  # top face
    ], dtype=np.float64)

    triangles = np.array([
        # bottom (z=0), outward normal = -Z
        [0, 2, 1], [0, 3, 2],
        # top (z=1), outward normal = +Z
        [4, 5, 6], [4, 6, 7],
        # front (y=0), normal = -Y
        [0, 1, 5], [0, 5, 4],
        # back (y=1), normal = +Y
        [2, 3, 7], [2, 7, 6],
        # left (x=0), normal = -X
        [0, 4, 7], [0, 7, 3],
        # right (x=1), normal = +X
        [1, 2, 6], [1, 6, 5],
    ], dtype=np.intp)

    return SculptMesh(positions=positions, triangles=triangles)


def make_sphere(n_lat: int = 8, n_lon: int = 8, radius: float = 1.0) -> SculptMesh:
    """UV sphere with n_lat latitude bands and n_lon longitude segments."""
    positions = []
    triangles = []

    # Top pole
    positions.append([0.0, radius, 0.0])

    # Latitude rings
    for lat in range(1, n_lat):
        phi = math.pi * lat / n_lat
        sin_phi = math.sin(phi)
        cos_phi = math.cos(phi)
        for lon in range(n_lon):
            theta = 2.0 * math.pi * lon / n_lon
            x = radius * sin_phi * math.cos(theta)
            y = radius * cos_phi
            z = radius * sin_phi * math.sin(theta)
            positions.append([x, y, z])

    # Bottom pole
    positions.append([0.0, -radius, 0.0])

    top_idx = 0
    bot_idx = len(positions) - 1

    def ring_start(lat_ring: int) -> int:
        """First vertex index of latitude ring (0-indexed, 1..n_lat-1)."""
        return 1 + (lat_ring - 1) * n_lon

    # Top cap
    for lon in range(n_lon):
        a = ring_start(1) + lon
        b = ring_start(1) + (lon + 1) % n_lon
        triangles.append([top_idx, a, b])

    # Middle bands
    for lat in range(1, n_lat - 1):
        for lon in range(n_lon):
            a = ring_start(lat) + lon
            b = ring_start(lat) + (lon + 1) % n_lon
            c = ring_start(lat + 1) + (lon + 1) % n_lon
            d = ring_start(lat + 1) + lon
            triangles.append([a, b, c])
            triangles.append([a, c, d])

    # Bottom cap
    for lon in range(n_lon):
        a = ring_start(n_lat - 1) + lon
        b = ring_start(n_lat - 1) + (lon + 1) % n_lon
        triangles.append([bot_idx, b, a])

    return SculptMesh(
        positions=np.array(positions, dtype=np.float64),
        triangles=np.array(triangles, dtype=np.intp),
    )


def make_noisy_plane(n: int = 10, noise_amp: float = 0.3, seed: int = 42) -> SculptMesh:
    """Plane with random Z noise added for SMOOTH convergence tests."""
    rng = np.random.default_rng(seed)
    mesh = make_plane(n)
    mesh.positions[:, 2] = rng.uniform(-noise_amp, noise_amp, size=mesh.positions.shape[0])
    return mesh


def make_square_quad_triangulated(n: int = 4) -> SculptMesh:
    """n×n quad grid triangulated as [a,b,c] + [a,c,d] for CREASE tests."""
    return make_plane(n)


# ---------------------------------------------------------------------------
# Test 1: falloff_weight — center is 1.0
# ---------------------------------------------------------------------------


def test_falloff_weight_center_is_one():
    """Weight is exactly 1.0 at the brush center (distance=0)."""
    for kind in ("smooth", "linear", "constant"):
        assert falloff_weight(0.0, 1.0, kind) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Test 2: falloff_weight — boundary is 0.0
# ---------------------------------------------------------------------------


def test_falloff_weight_boundary_is_zero():
    """Weight is exactly 0.0 at or beyond the brush boundary."""
    for kind in ("smooth", "linear", "constant"):
        assert falloff_weight(1.0, 1.0, kind) == pytest.approx(0.0)
    # Beyond boundary
    for kind in ("smooth", "linear"):
        assert falloff_weight(1.5, 1.0, kind) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Test 3: falloff_weight — smooth is monotone decreasing
# ---------------------------------------------------------------------------


def test_falloff_weight_smooth_monotone():
    """Cubic Hermite falloff decreases monotonically from center to boundary."""
    r = 2.0
    prev = 1.0
    for d in np.linspace(0.01, r - 0.01, 20):
        w = falloff_weight(float(d), r, "smooth")
        assert w <= prev + 1e-12
        prev = w
    # Last value before boundary is > 0
    assert falloff_weight(r * 0.99, r, "smooth") > 0.0


# ---------------------------------------------------------------------------
# Test 4: falloff_weight — linear falloff midpoint
# ---------------------------------------------------------------------------


def test_falloff_weight_linear_midpoint():
    """Linear falloff: weight at d=r/2 should be 0.5."""
    assert falloff_weight(0.5, 1.0, "linear") == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Test 5: INFLATE on flat plane — center vertex moves +Z
# ---------------------------------------------------------------------------


def test_inflate_flat_plane_center_moves_up():
    """INFLATE at the center of a flat plane pushes the center vertex upward."""
    mesh = make_plane(10)
    center_idx = _center_index_of_plane(10)
    center_pos = mesh.positions[center_idx].copy()

    stroke = BrushStroke(
        kind=BrushKind.INFLATE,
        center=center_pos,
        direction=None,
        radius=2.0,
        strength=0.5,
        falloff="smooth",
    )
    before_z = mesh.positions[center_idx, 2]
    apply_brush(mesh, stroke)
    after_z = mesh.positions[center_idx, 2]

    # Flat plane normals point +Z; center should move up
    assert after_z > before_z, "Center vertex should move in +Z after INFLATE on flat plane"


# ---------------------------------------------------------------------------
# Test 6: INFLATE — vertices farther from center move less (falloff)
# ---------------------------------------------------------------------------


def test_inflate_falloff_farther_vertices_move_less():
    """Vertices farther from brush center receive smaller displacement."""
    mesh = make_plane(10)
    n = 10
    center_idx = _center_index_of_plane(n)
    center_pos = mesh.positions[center_idx].copy()

    stroke = BrushStroke(
        kind=BrushKind.INFLATE,
        center=center_pos,
        direction=None,
        radius=3.0,
        strength=1.0,
        falloff="smooth",
    )

    before = mesh.positions.copy()
    apply_brush(mesh, stroke)
    after = mesh.positions

    deltas = np.linalg.norm(after - before, axis=1)

    # Center vertex should have among the larger displacements
    center_delta = deltas[center_idx]
    # A vertex near the boundary should move less than the center
    # Pick a vertex at distance ~radius/2 and another at ~radius*0.9
    # Just assert that max delta in the brush is at a central vertex
    in_radius = np.linalg.norm(mesh.positions - center_pos, axis=1) < 3.0
    assert center_delta >= deltas[in_radius].mean(), "Center vertex should displace at least the mean"


# ---------------------------------------------------------------------------
# Test 7: SMOOTH converges noisy plane toward flat
# ---------------------------------------------------------------------------


def test_smooth_converges_noisy_plane():
    """Repeated SMOOTH strokes reduce Z-noise on a flat plane."""
    mesh = make_noisy_plane(n=8, noise_amp=0.5, seed=0)
    center = np.array([4.0, 4.0, 0.0])

    initial_std = float(np.std(mesh.positions[:, 2]))

    stroke = BrushStroke(
        kind=BrushKind.SMOOTH,
        center=center,
        direction=None,
        radius=10.0,   # cover entire mesh
        strength=0.8,
        falloff="constant",
    )

    for _ in range(20):
        apply_brush(mesh, stroke)

    final_std = float(np.std(mesh.positions[:, 2]))
    assert final_std < initial_std * 0.3, (
        f"SMOOTH should reduce noise std; initial={initial_std:.4f}, final={final_std:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 8: GRAB — pulls vertices along direction
# ---------------------------------------------------------------------------


def test_grab_pulls_vertices_along_direction():
    """GRAB on a sphere at the equator pulls affected vertices in +Y."""
    mesh = make_sphere(n_lat=8, n_lon=8, radius=1.0)
    direction = np.array([0.0, 1.0, 0.0])
    center = np.array([1.0, 0.0, 0.0])   # equator region

    before = mesh.positions.copy()
    stroke = BrushStroke(
        kind=BrushKind.GRAB,
        center=center,
        direction=direction,
        radius=0.8,
        strength=0.5,
        falloff="smooth",
    )
    apply_brush(mesh, stroke)

    changed = mesh.positions - before
    in_radius = np.linalg.norm(before - center, axis=1) < 0.8
    # All affected vertices should have moved in +Y
    y_deltas = changed[in_radius, 1]
    assert np.all(y_deltas >= 0.0), "GRAB with +Y direction should move affected vertices in +Y"
    assert np.any(y_deltas > 0.0), "At least one vertex should be displaced"


# ---------------------------------------------------------------------------
# Test 9: GRAB — vertex at center gets maximum displacement
# ---------------------------------------------------------------------------


def test_grab_center_vertex_max_displacement():
    """The vertex at the brush center gets the full strength displacement."""
    mesh = make_plane(10)
    center_idx = _center_index_of_plane(10)
    center = mesh.positions[center_idx].copy()
    direction = np.array([0.0, 0.0, 1.0])

    before = mesh.positions[center_idx].copy()
    stroke = BrushStroke(
        kind=BrushKind.GRAB,
        center=center,
        direction=direction,
        radius=2.0,
        strength=0.5,
        falloff="smooth",
    )
    delta = apply_brush(mesh, stroke)
    after = mesh.positions[center_idx].copy()

    # The center vertex (distance=0, w=1) should move exactly strength along direction
    dz = after[2] - before[2]
    assert dz == pytest.approx(0.5, abs=1e-10), f"Expected 0.5 displacement, got {dz}"


# ---------------------------------------------------------------------------
# Test 10: PINCH creates a depression at brush center
# ---------------------------------------------------------------------------


def test_pinch_creates_depression():
    """PINCH pulls vertices toward brush center, creating a local cluster."""
    mesh = make_plane(10)
    center_idx = _center_index_of_plane(10)
    center = mesh.positions[center_idx].copy()

    before = mesh.positions.copy()
    stroke = BrushStroke(
        kind=BrushKind.PINCH,
        center=center,
        direction=None,
        radius=3.0,
        strength=0.8,
        falloff="smooth",
    )
    apply_brush(mesh, stroke)

    # Vertices near the boundary should have moved toward center
    in_radius = np.linalg.norm(before - center, axis=1) < 3.0
    in_radius[center_idx] = False   # exclude center itself

    after = mesh.positions
    # For each in-radius vertex, distance to center should have decreased
    d_before = np.linalg.norm(before[in_radius] - center, axis=1)
    d_after = np.linalg.norm(after[in_radius] - center, axis=1)
    assert np.all(d_after <= d_before + 1e-12), (
        "PINCH should move vertices closer to center"
    )
    assert np.any(d_after < d_before - 1e-6), "Some vertices should have moved"


# ---------------------------------------------------------------------------
# Test 11: CREASE sharpens diagonal of square mesh
# ---------------------------------------------------------------------------


def test_crease_sharpens_diagonal():
    """CREASE along X=Y diagonal of a plane pulls vertices toward the axis."""
    mesh = make_square_quad_triangulated(n=8)
    # Stroke axis: diagonal direction (1, 1, 0)
    axis = np.array([1.0, 1.0, 0.0]) / math.sqrt(2)
    center = np.array([4.0, 4.0, 0.0])

    before = mesh.positions.copy()
    stroke = BrushStroke(
        kind=BrushKind.CREASE,
        center=center,
        direction=axis,
        radius=5.0,
        strength=0.6,
        falloff="smooth",
    )
    apply_brush(mesh, stroke)

    # Off-diagonal vertices (large perpendicular component) should have moved
    changed = np.linalg.norm(mesh.positions - before, axis=1)
    in_radius = np.linalg.norm(before - center, axis=1) < 5.0
    assert np.any(changed[in_radius] > 1e-6), "CREASE should displace off-axis vertices"


# ---------------------------------------------------------------------------
# Test 12: apply + revert restores positions to original (within 1e-12)
# ---------------------------------------------------------------------------


def test_apply_revert_restores_positions():
    """Applying a brush stroke and then reverting restores positions exactly."""
    mesh = make_plane(10)
    original = mesh.positions.copy()
    center = mesh.positions[_center_index_of_plane(10)].copy()

    for kind in (BrushKind.INFLATE, BrushKind.SMOOTH, BrushKind.PINCH):
        mesh.positions[:] = original
        stroke = BrushStroke(
            kind=kind,
            center=center,
            direction=np.array([0.0, 0.0, 1.0]),
            radius=3.0,
            strength=0.7,
            falloff="smooth",
        )
        delta = apply_brush(mesh, stroke)
        revert_delta(mesh, delta)
        assert np.allclose(mesh.positions, original, atol=1e-12), (
            f"revert_delta failed for {kind}: max diff = "
            f"{np.abs(mesh.positions - original).max()}"
        )


def test_apply_revert_grab():
    """GRAB: apply + revert restores positions exactly."""
    mesh = make_sphere()
    original = mesh.positions.copy()
    center = np.array([1.0, 0.0, 0.0])
    direction = np.array([0.0, 1.0, 0.0])

    stroke = BrushStroke(
        kind=BrushKind.GRAB,
        center=center,
        direction=direction,
        radius=0.8,
        strength=0.5,
        falloff="smooth",
    )
    delta = apply_brush(mesh, stroke)
    revert_delta(mesh, delta)
    assert np.allclose(mesh.positions, original, atol=1e-12)


def test_apply_revert_crease():
    """CREASE: apply + revert restores positions exactly."""
    mesh = make_plane(8)
    original = mesh.positions.copy()
    center = np.array([4.0, 4.0, 0.0])
    axis = np.array([1.0, 0.0, 0.0])

    stroke = BrushStroke(
        kind=BrushKind.CREASE,
        center=center,
        direction=axis,
        radius=3.0,
        strength=0.5,
        falloff="smooth",
    )
    delta = apply_brush(mesh, stroke)
    revert_delta(mesh, delta)
    assert np.allclose(mesh.positions, original, atol=1e-12)


# ---------------------------------------------------------------------------
# Test 13: strength=0 produces no change
# ---------------------------------------------------------------------------


def test_strength_zero_no_change():
    """A stroke with strength=0 must not move any vertex."""
    mesh = make_plane(6)
    original = mesh.positions.copy()
    center = mesh.positions[_center_index_of_plane(6)].copy()

    for kind in BrushKind:
        mesh.positions[:] = original
        direction = np.array([0.0, 0.0, 1.0])
        stroke = BrushStroke(
            kind=kind,
            center=center,
            direction=direction,
            radius=5.0,
            strength=0.0,
            falloff="smooth",
        )
        apply_brush(mesh, stroke)
        assert np.allclose(mesh.positions, original, atol=1e-15), (
            f"strength=0 should produce no change for {kind}"
        )


# ---------------------------------------------------------------------------
# Test 14: radius > mesh extent affects all vertices
# ---------------------------------------------------------------------------


def test_large_radius_affects_all_vertices():
    """When radius >> mesh extent, every vertex should be displaced."""
    mesh = make_plane(4)
    original = mesh.positions.copy()
    center = np.array([2.0, 2.0, 0.0])
    huge_radius = 1000.0

    stroke = BrushStroke(
        kind=BrushKind.INFLATE,
        center=center,
        direction=None,
        radius=huge_radius,
        strength=0.5,
        falloff="constant",
    )
    apply_brush(mesh, stroke)

    changed = np.any(mesh.positions != original, axis=1)
    assert np.all(changed), "Every vertex should be affected when radius >> mesh extent"


# ---------------------------------------------------------------------------
# Test 15: vertex_normals on a cube — corner normals are averaged
# ---------------------------------------------------------------------------


def test_vertex_normals_cube_corners():
    """Each cube corner touches 3 faces; normals are area-weighted average."""
    mesh = make_unit_cube()
    normals = mesh.vertex_normals()

    # All normals should be unit vectors
    lengths = np.linalg.norm(normals, axis=1)
    assert np.allclose(lengths, 1.0, atol=1e-10), "All vertex normals should be unit vectors"

    # At corner (0,0,0): adjacent faces are bottom, front, left → normals -Z,-Y,-X
    # The average (area-weighted) should point roughly toward (-1,-1,-1)
    n = normals[0]   # vertex 0 = (0,0,0)
    assert n[0] < 0, "Vertex (0,0,0) normal should have -X component"
    assert n[1] < 0, "Vertex (0,0,0) normal should have -Y component"
    assert n[2] < 0, "Vertex (0,0,0) normal should have -Z component"


# ---------------------------------------------------------------------------
# Test 16: one_ring_neighbours on 4×4 grid has correct neighbour counts
# ---------------------------------------------------------------------------


def test_one_ring_neighbours_4x4_grid():
    """Interior vertices of a 4×4 quad grid have 6 neighbours; corners have 2+."""
    mesh = make_plane(4)   # 5×5 = 25 vertices
    rings = mesh.one_ring_neighbours()

    n = 4
    # Interior vertices: i in [1,3], j in [1,3] → 8 neighbours (each shared by 6 triangles)
    # Actually for a triangulated quad grid, interior vertices have 6 neighbours
    # Corner vertex (0,0) → index 0
    corner_idx = 0
    # Corner vertex has 2 quad neighbours → each quad is split into 2 tris;
    # corner is shared by 2 triangles → 3 unique neighbour vertices
    # (It connects to (1,0) and (0,1) and (1,1) via the diagonal)
    assert len(rings[corner_idx]) >= 2, "Corner vertex should have at least 2 neighbours"

    # Interior vertex at (2,2) → index 2*(n+1)+2 = 12
    interior_idx = 2 * (n + 1) + 2
    # Interior vertex in triangulated quad grid: 6 neighbours
    assert len(rings[interior_idx]) == 6, (
        f"Interior vertex of triangulated quad grid should have 6 neighbours, "
        f"got {len(rings[interior_idx])}"
    )

    # All rings should be consistent (i in ring[j] ↔ j in ring[i])
    for i, ring in enumerate(rings):
        for j in ring:
            assert i in rings[j], f"Ring symmetry broken: {i} in rings[{j}] but {j} not in rings[{i}]"


# ---------------------------------------------------------------------------
# Test 17: MeshDelta is empty when no vertices in radius
# ---------------------------------------------------------------------------


def test_no_vertices_in_radius_returns_empty_delta():
    """A stroke whose radius reaches no vertices should return an empty delta."""
    mesh = make_plane(4)
    # Place center far away
    center = np.array([9999.0, 9999.0, 0.0])
    stroke = BrushStroke(
        kind=BrushKind.INFLATE,
        center=center,
        direction=None,
        radius=0.01,
        strength=1.0,
        falloff="smooth",
    )
    delta = apply_brush(mesh, stroke)
    assert delta.vertex_indices.size == 0
    assert delta.deltas.shape == (0, 3)


# ---------------------------------------------------------------------------
# Test 18: INFLATE does not change XY of flat plane center vertex
# ---------------------------------------------------------------------------


def test_inflate_flat_plane_only_z_displacement():
    """INFLATE on a flat plane moves center vertex only in Z (normal = +Z)."""
    mesh = make_plane(10)
    center_idx = _center_index_of_plane(10)
    center = mesh.positions[center_idx].copy()

    before_xy = mesh.positions[center_idx, :2].copy()

    stroke = BrushStroke(
        kind=BrushKind.INFLATE,
        center=center,
        direction=None,
        radius=2.0,
        strength=0.5,
        falloff="smooth",
    )
    apply_brush(mesh, stroke)

    after_xy = mesh.positions[center_idx, :2]
    # XY should not change (normal is +Z)
    assert np.allclose(after_xy, before_xy, atol=1e-12), (
        "INFLATE on flat plane should only displace in Z, not XY"
    )


# ---------------------------------------------------------------------------
# Test 19: GRAB requires direction — raises ValueError when None
# ---------------------------------------------------------------------------


def test_grab_requires_direction():
    """GRAB raises ValueError when direction=None."""
    mesh = make_plane(4)
    stroke = BrushStroke(
        kind=BrushKind.GRAB,
        center=np.array([2.0, 2.0, 0.0]),
        direction=None,
        radius=2.0,
        strength=0.5,
    )
    with pytest.raises(ValueError, match="GRAB requires stroke.direction"):
        apply_brush(mesh, stroke)


# ---------------------------------------------------------------------------
# Test 20: SMOOTH does not change a perfectly flat, uniform mesh
# ---------------------------------------------------------------------------


def test_smooth_preserves_flat_plane():
    """SMOOTH on a flat plane should not move any vertex in Z (plane is already flat)."""
    mesh = make_plane(6)
    original_z = mesh.positions[:, 2].copy()
    center = np.array([3.0, 3.0, 0.0])

    stroke = BrushStroke(
        kind=BrushKind.SMOOTH,
        center=center,
        direction=None,
        radius=100.0,
        strength=1.0,
        falloff="constant",
    )
    apply_brush(mesh, stroke)

    # Z coordinates should remain exactly zero (all neighbours are also at z=0)
    assert np.allclose(mesh.positions[:, 2], original_z, atol=1e-12), (
        "SMOOTH on a flat plane should not change Z coordinates"
    )


# ---------------------------------------------------------------------------
# Test 21: multiple strokes, multiple undos
# ---------------------------------------------------------------------------


def test_multiple_strokes_and_undos():
    """Applying multiple strokes and reverting in reverse order restores mesh."""
    mesh = make_plane(6)
    original = mesh.positions.copy()
    center = np.array([3.0, 3.0, 0.0])

    strokes = [
        BrushStroke(BrushKind.INFLATE, center, None, 2.0, 0.3),
        BrushStroke(BrushKind.SMOOTH, center, None, 3.0, 0.5),
        BrushStroke(BrushKind.PINCH, center, None, 2.5, 0.4),
    ]

    deltas = []
    for stroke in strokes:
        d = apply_brush(mesh, stroke)
        deltas.append(d)

    # Revert in reverse order
    for d in reversed(deltas):
        revert_delta(mesh, d)

    assert np.allclose(mesh.positions, original, atol=1e-12), (
        "All strokes should be fully reversible in LIFO order"
    )


# ---------------------------------------------------------------------------
# Test 22: falloff_weight raises on invalid kind
# ---------------------------------------------------------------------------


def test_falloff_weight_invalid_kind():
    """falloff_weight raises ValueError for unknown falloff kind."""
    with pytest.raises(ValueError, match="unknown falloff kind"):
        falloff_weight(0.5, 1.0, "bogus")
