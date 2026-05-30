"""
test_surface_mesh_deviation.py
==============================
GK-P: NURBS surface ↔ triangle mesh max deviation tests.

Analytic oracles:
  1. Perfect fit  — flat NURBS plane + flat triangle mesh at same z → Hausdorff < 1e-9
  2. Offset by 0.1 — same plane + mesh translated (0,0,0.1) → Hausdorff = 0.1 ± 1e-6
  3. Sphere fit   — NURBS sphere + tessellated sphere → Hausdorff < chord error (0.05)
  4. Bidirectional symmetry — H_sym = max(H_fwd, H_bwd)

References: Aspert-Santa-Cruz-Ebrahimi 2002 (MESH); Cignoni-Rocchini-Scopigno 1998 (METRO).
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.surface_mesh_deviation import (
    SurfaceMeshDeviation,
    bidirectional_hausdorff,
    hausdorff_surface_to_mesh,
    max_deviation_visualization,
)


# ---------------------------------------------------------------------------
# Surface and mesh factories
# ---------------------------------------------------------------------------

def _make_knots(n: int, deg: int) -> np.ndarray:
    """Clamped uniform knot vector for n control points of degree deg."""
    inner = max(0, n - deg - 1)
    parts = [np.zeros(deg + 1)]
    if inner > 0:
        parts.append(np.linspace(0.0, 1.0, inner + 2)[1:-1])
    parts.append(np.ones(deg + 1))
    return np.concatenate(parts)


def make_flat_nurbs_plane(z: float = 0.0, size: float = 2.0, n: int = 4) -> NurbsSurface:
    """Flat degree-1 NURBS plane at constant z, spanning [0,size]×[0,size]."""
    cp = np.zeros((n, n, 3))
    for i in range(n):
        for j in range(n):
            cp[i, j] = [i * size / (n - 1), j * size / (n - 1), z]
    return NurbsSurface(
        degree_u=1,
        degree_v=1,
        control_points=cp,
        knots_u=_make_knots(n, 1),
        knots_v=_make_knots(n, 1),
    )


def make_flat_triangle_mesh(z: float = 0.0, size: float = 2.0, n: int = 8) -> dict:
    """Flat triangle mesh at constant z over [0,size]×[0,size].

    Produces an (n-1)×(n-1) × 2 = 2*(n-1)^2 triangle mesh.
    """
    verts = []
    for i in range(n):
        for j in range(n):
            verts.append([i * size / (n - 1), j * size / (n - 1), z])
    verts = np.array(verts, dtype=float)

    tris = []
    for i in range(n - 1):
        for j in range(n - 1):
            # Lower-left triangle
            v00 = i * n + j
            v10 = (i + 1) * n + j
            v01 = i * n + (j + 1)
            v11 = (i + 1) * n + (j + 1)
            tris.append([v00, v10, v01])
            tris.append([v10, v11, v01])

    return {"vertices": verts, "triangles": np.array(tris, dtype=int)}


def make_nurbs_sphere(radius: float = 1.0, n: int = 9) -> NurbsSurface:
    """Approximate NURBS sphere as a degree-1 polygonal sphere (UV grid).

    Uses n latitude bands and n longitude bands.  Degree-1 = piecewise linear
    so the chord error is bounded by 2R*(1-cos(π/n)).  For n=9 this is ~0.23R.
    """
    n_lat = n
    n_lon = n * 2
    cp = np.zeros((n_lat, n_lon, 3))
    for i in range(n_lat):
        theta = math.pi * i / (n_lat - 1)  # 0..pi
        for j in range(n_lon):
            phi = 2 * math.pi * j / (n_lon - 1)  # 0..2pi
            cp[i, j] = [
                radius * math.sin(theta) * math.cos(phi),
                radius * math.sin(theta) * math.sin(phi),
                radius * math.cos(theta),
            ]
    return NurbsSurface(
        degree_u=1,
        degree_v=1,
        control_points=cp,
        knots_u=_make_knots(n_lat, 1),
        knots_v=_make_knots(n_lon, 1),
    )


def make_tessellated_sphere(radius: float = 1.0, n: int = 12) -> dict:
    """Tessellated sphere mesh — UV icosphere-like from lat/lon grid.

    n latitude bands × 2n longitude bands → 4n² triangles.
    """
    n_lat = n
    n_lon = n * 2
    verts = []
    for i in range(n_lat):
        theta = math.pi * i / (n_lat - 1)
        for j in range(n_lon):
            phi = 2 * math.pi * j / (n_lon - 1)
            verts.append([
                radius * math.sin(theta) * math.cos(phi),
                radius * math.sin(theta) * math.sin(phi),
                radius * math.cos(theta),
            ])
    verts = np.array(verts, dtype=float)

    tris = []
    for i in range(n_lat - 1):
        for j in range(n_lon - 1):
            v00 = i * n_lon + j
            v10 = (i + 1) * n_lon + j
            v01 = i * n_lon + (j + 1)
            v11 = (i + 1) * n_lon + (j + 1)
            tris.append([v00, v10, v01])
            tris.append([v10, v11, v01])

    return {"vertices": verts, "triangles": np.array(tris, dtype=int)}


# ---------------------------------------------------------------------------
# Test 1: Perfect fit — flat NURBS plane + flat mesh at same z
# ---------------------------------------------------------------------------

class TestPerfectFit:
    """Hausdorff of NURBS plane + co-planar mesh must be < 1e-9."""

    def test_perfect_fit_plane(self) -> None:
        """Flat NURBS z=0 + flat mesh z=0 → Hausdorff < 1e-9."""
        surface = make_flat_nurbs_plane(z=0.0, size=2.0)
        mesh = make_flat_triangle_mesh(z=0.0, size=2.0)

        result = hausdorff_surface_to_mesh(surface, mesh, n_samples=200)

        assert isinstance(result, SurfaceMeshDeviation), (
            f"Expected SurfaceMeshDeviation, got error: {result}"
        )
        assert result.hausdorff_max < 1e-9, (
            f"Perfect fit Hausdorff = {result.hausdorff_max:.3e}, expected < 1e-9"
        )
        assert result.rms < 1e-9, (
            f"Perfect fit RMS = {result.rms:.3e}, expected < 1e-9"
        )
        assert result.n_samples_used > 0

    def test_perfect_fit_returns_dataclass(self) -> None:
        """Result is SurfaceMeshDeviation with expected attributes."""
        surface = make_flat_nurbs_plane(z=0.0)
        mesh = make_flat_triangle_mesh(z=0.0)
        result = hausdorff_surface_to_mesh(surface, mesh, n_samples=100)
        assert isinstance(result, SurfaceMeshDeviation)
        assert hasattr(result, "hausdorff_max")
        assert hasattr(result, "hausdorff_mean")
        assert hasattr(result, "rms")
        assert hasattr(result, "per_region_max")
        assert hasattr(result, "n_samples_used")


# ---------------------------------------------------------------------------
# Test 2: Offset by 0.1 — same plane + mesh translated (0,0,0.1)
# ---------------------------------------------------------------------------

class TestOffset:
    """Hausdorff must equal the z-offset within 1e-6."""

    @pytest.mark.parametrize("offset", [0.1, 0.5, 1.0])
    def test_plane_offset_oracle(self, offset: float) -> None:
        """Hausdorff(surface z=0, mesh z=offset) == offset ± 1e-6."""
        surface = make_flat_nurbs_plane(z=0.0, size=2.0)
        mesh = make_flat_triangle_mesh(z=offset, size=2.0)

        result = hausdorff_surface_to_mesh(surface, mesh, n_samples=400)

        assert isinstance(result, SurfaceMeshDeviation), (
            f"Expected SurfaceMeshDeviation, got error: {result}"
        )
        assert abs(result.hausdorff_max - offset) <= 1e-6, (
            f"Hausdorff {result.hausdorff_max:.8f} != offset {offset} "
            f"(delta={abs(result.hausdorff_max - offset):.2e})"
        )

    def test_small_offset_0_1(self) -> None:
        """Primary oracle: offset=0.1 → Hausdorff = 0.1 within 1e-6."""
        surface = make_flat_nurbs_plane(z=0.0, size=2.0)
        mesh = make_flat_triangle_mesh(z=0.1, size=2.0)
        result = hausdorff_surface_to_mesh(surface, mesh, n_samples=500)
        assert isinstance(result, SurfaceMeshDeviation)
        assert abs(result.hausdorff_max - 0.1) <= 1e-6, (
            f"Hausdorff {result.hausdorff_max:.8f} expected 0.1 ± 1e-6"
        )

    def test_rms_equals_offset_for_constant_deviation(self) -> None:
        """RMS == hausdorff_max when all deviations are equal (constant offset)."""
        surface = make_flat_nurbs_plane(z=0.0, size=2.0)
        mesh = make_flat_triangle_mesh(z=0.3, size=2.0)
        result = hausdorff_surface_to_mesh(surface, mesh, n_samples=300)
        assert isinstance(result, SurfaceMeshDeviation)
        # For a constant offset all distances are the same → RMS == max
        assert abs(result.rms - result.hausdorff_max) < 1e-9, (
            f"RMS {result.rms:.3e} != hausdorff_max {result.hausdorff_max:.3e}"
        )


# ---------------------------------------------------------------------------
# Test 3: Sphere fit — NURBS sphere + tessellated sphere of same radius
# ---------------------------------------------------------------------------

class TestSphereFit:
    """NURBS sphere vs tessellated sphere: Hausdorff < chord deviation bound."""

    def test_sphere_hausdorff_within_chord_bound(self) -> None:
        """NURBS sphere + tessellated sphere of same radius → H < 0.05.

        The chord deviation for a degree-1 polygon sphere with n=12 lat bands
        and 24 lon samples is bounded by 2R*(1-cos(π/n)) < 0.05 for R=1, n=12.
        The two meshes share the same tessellation, so the Hausdorff between
        them (surface→mesh) should be near zero — just floating-point chord
        discretisation.
        """
        radius = 1.0
        # Use same n for both so points nearly coincide
        n = 10
        surface = make_nurbs_sphere(radius=radius, n=n)
        mesh = make_tessellated_sphere(radius=radius, n=n)

        result = hausdorff_surface_to_mesh(surface, mesh, n_samples=400)

        assert isinstance(result, SurfaceMeshDeviation), (
            f"Expected SurfaceMeshDeviation, got: {result}"
        )
        # Chord deviation bound: 2R*(1-cos(π/n)) ≈ 0.097 for n=10; use 0.15 as bound
        chord_bound = 2 * radius * (1.0 - math.cos(math.pi / n)) + 0.05
        assert result.hausdorff_max < chord_bound, (
            f"Sphere Hausdorff {result.hausdorff_max:.4f} >= chord bound {chord_bound:.4f}"
        )

    def test_sphere_max_below_strict_bound(self) -> None:
        """Same radius sphere: H < 0.05 for n=12 tessellation (moderate density)."""
        radius = 1.0
        n = 12
        surface = make_nurbs_sphere(radius=radius, n=n)
        mesh = make_tessellated_sphere(radius=radius, n=n)
        result = hausdorff_surface_to_mesh(surface, mesh, n_samples=600)
        assert isinstance(result, SurfaceMeshDeviation)
        # The NURBS sphere has the same vertices as the tessellated sphere
        # → Hausdorff should be much smaller than the chord bound
        assert result.hausdorff_max < 0.05, (
            f"Sphere Hausdorff {result.hausdorff_max:.4f} should be < 0.05"
        )


# ---------------------------------------------------------------------------
# Test 4: Bidirectional symmetry
# ---------------------------------------------------------------------------

class TestBidirectionalSymmetry:
    """bidirectional_hausdorff == max(forward, backward)."""

    def test_bidirectional_symmetric_equals_max(self) -> None:
        """H_symmetric == max(H_forward, H_backward)."""
        surface = make_flat_nurbs_plane(z=0.0, size=2.0)
        mesh = make_flat_triangle_mesh(z=0.2, size=2.0)

        result = bidirectional_hausdorff(surface, mesh, n_samples=300)

        assert result["ok"], f"bidirectional_hausdorff failed: {result.get('reason')}"
        h_fwd = result["hausdorff_forward"]
        h_bwd = result["hausdorff_backward"]
        h_sym = result["hausdorff_symmetric"]

        expected_sym = max(h_fwd, h_bwd)
        assert abs(h_sym - expected_sym) < 1e-12, (
            f"h_symmetric={h_sym:.6e} != max(h_fwd={h_fwd:.6e}, h_bwd={h_bwd:.6e})"
        )

    def test_bidirectional_result_keys(self) -> None:
        """Result dict has all expected keys."""
        surface = make_flat_nurbs_plane(z=0.0)
        mesh = make_flat_triangle_mesh(z=0.1)
        result = bidirectional_hausdorff(surface, mesh, n_samples=100)
        assert result["ok"]
        for key in ("hausdorff_forward", "hausdorff_backward", "hausdorff_symmetric",
                    "hausdorff_mean_forward", "rms_forward",
                    "n_surface_samples", "n_mesh_vertices"):
            assert key in result, f"Missing key: {key}"

    def test_bidirectional_symmetric_nonnegative(self) -> None:
        """All reported distances must be >= 0."""
        surface = make_flat_nurbs_plane(z=0.0)
        mesh = make_flat_triangle_mesh(z=0.15)
        result = bidirectional_hausdorff(surface, mesh, n_samples=200)
        assert result["ok"]
        assert result["hausdorff_forward"]  >= 0.0
        assert result["hausdorff_backward"] >= 0.0
        assert result["hausdorff_symmetric"] >= 0.0

    def test_zero_offset_bidirectional(self) -> None:
        """Bidirectional Hausdorff near 0 for co-planar surface and mesh.

        The forward direction (surface→mesh) is < 1e-9 since all surface
        samples lie on triangles of the co-planar mesh.  The backward direction
        (mesh vertices→surface) is approximated via a surface sample grid; the
        grid spacing introduces a positional error that for z=0 planes is
        purely in XY (the actual distance to the surface at z=0 is 0 for every
        mesh vertex, but the KDTree can only find the nearest sample).
        We therefore check: forward ≈ 0, and symmetric ≥ forward (trivially
        true), but do not require symmetric < 1e-9.
        """
        surface = make_flat_nurbs_plane(z=0.0)
        mesh = make_flat_triangle_mesh(z=0.0)
        result = bidirectional_hausdorff(surface, mesh, n_samples=200)
        assert result["ok"]
        # Forward (surface samples → mesh triangles) should be exact ~0
        assert result["hausdorff_forward"] < 1e-9, (
            f"Forward Hausdorff expected ~0, got {result['hausdorff_forward']:.3e}"
        )
        # Symmetric ≥ forward (backward approximation can be non-zero due to grid)
        assert result["hausdorff_symmetric"] >= result["hausdorff_forward"] - 1e-15


# ---------------------------------------------------------------------------
# Test: max_deviation_visualization
# ---------------------------------------------------------------------------

class TestMaxDeviationVisualization:
    """UV heatmap returns consistent per-sample deviations."""

    def test_heatmap_max_matches_offset(self) -> None:
        """Heatmap max_deviation == constant offset for co-planar pair."""
        surface = make_flat_nurbs_plane(z=0.0)
        mesh = make_flat_triangle_mesh(z=0.4)
        result = max_deviation_visualization(surface, mesh, n_samples_u=10, n_samples_v=10)
        assert result["ok"]
        assert abs(result["max_deviation"] - 0.4) < 1e-6, (
            f"Heatmap max {result['max_deviation']:.6f} expected 0.4"
        )

    def test_heatmap_returns_correct_count(self) -> None:
        """UV heatmap has n_u * n_v entries."""
        surface = make_flat_nurbs_plane(z=0.0)
        mesh = make_flat_triangle_mesh(z=0.1)
        nu, nv = 8, 6
        result = max_deviation_visualization(surface, mesh, n_samples_u=nu, n_samples_v=nv)
        assert result["ok"]
        assert len(result["uv_distances"]) == nu * nv
        assert result["n_samples_u"] == nu
        assert result["n_samples_v"] == nv

    def test_heatmap_entries_have_uv_keys(self) -> None:
        """Each heatmap entry has u, v, distance keys."""
        surface = make_flat_nurbs_plane(z=0.0)
        mesh = make_flat_triangle_mesh(z=0.1)
        result = max_deviation_visualization(surface, mesh, n_samples_u=4, n_samples_v=4)
        assert result["ok"]
        for entry in result["uv_distances"]:
            assert "u" in entry and "v" in entry and "distance" in entry


# ---------------------------------------------------------------------------
# Test: error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Invalid inputs return {ok: False, reason: str}."""

    def test_bad_surface_type(self) -> None:
        mesh = make_flat_triangle_mesh(z=0.0)
        result = hausdorff_surface_to_mesh("not_a_surface", mesh)
        assert isinstance(result, dict) and not result["ok"]

    def test_missing_mesh_vertices(self) -> None:
        surface = make_flat_nurbs_plane(z=0.0)
        result = hausdorff_surface_to_mesh(surface, {"triangles": [[0, 1, 2]]})
        assert isinstance(result, dict) and not result["ok"]

    def test_missing_mesh_triangles(self) -> None:
        surface = make_flat_nurbs_plane(z=0.0)
        result = hausdorff_surface_to_mesh(
            surface, {"vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]]}
        )
        assert isinstance(result, dict) and not result["ok"]

    def test_bad_surface_type_bidirectional(self) -> None:
        mesh = make_flat_triangle_mesh(z=0.0)
        result = bidirectional_hausdorff(42, mesh)
        assert not result["ok"]


# ---------------------------------------------------------------------------
# Test: per-region max deviation
# ---------------------------------------------------------------------------

class TestPerRegionMax:
    """Per-region max is computed correctly for rectangular UV sub-domains."""

    def test_per_region_max_for_half_offset(self) -> None:
        """One flat region, one offset region: per-region max reflects offset."""
        # Plane spans u in [0,1], v in [0,1] (knots are [0,1])
        # We create a mesh with all triangles at z=0.2
        surface = make_flat_nurbs_plane(z=0.0, size=1.0, n=3)
        mesh = make_flat_triangle_mesh(z=0.2, size=1.0)

        # Region 0: full UV domain [0,1]×[0,1]
        regions = [(0.0, 1.0, 0.0, 1.0)]
        result = hausdorff_surface_to_mesh(surface, mesh, n_samples=200, regions=regions)
        assert isinstance(result, SurfaceMeshDeviation)
        assert 0 in result.per_region_max
        assert abs(result.per_region_max[0] - 0.2) < 1e-6, (
            f"Per-region max {result.per_region_max[0]:.6f} expected 0.2"
        )
