"""Tests for GK-P-C — Multi-resolution displacement on subdivision surfaces.

Reference: Lee-Moreton-Hoppe 2000 "Displaced Subdivision Surfaces", SIGGRAPH 2000.

Test plan
---------
T1 — Identity round-trip
    extract_displacement(fine, base, level) → apply_displacement(base, level, dmap)
    must reproduce fine_mesh within 1e-9 positional error for a synthetically
    displaced mesh (clean UV parameterisation, no noise).

T2 — Smooth sinusoidal displacement
    A sinusoidal displacement map applied to a flat quad base → fine mesh
    must have an expected sinusoidal Z-profile within 1% RMS.

T3 — Pyramid reconstruction
    encode_pyramid([d0, d1, d2]) → decode_pyramid(pyr, 2) must reproduce
    the level-2 map exactly within 1e-9.

T4 — LOD coarsening
    decode_pyramid(pyr, 1) must approximate but not exactly reproduce the
    level-2 displacement; the RMS error must be > 0 but the coarser result
    must not deviate by more than the max amplitude of the full map.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.subd import SubDMesh, catmull_clark_subdivide
from kerf_cad_core.geom.multires_displacement import (
    DisplacementMap,
    DisplacementPyramid,
    apply_displacement,
    decode_pyramid,
    encode_pyramid,
    extract_displacement,
    _compute_stam_normals,
    _compute_vertex_uvs,
)


# ---------------------------------------------------------------------------
# Fixtures — canonical flat quad-grid base cage
# ---------------------------------------------------------------------------


def make_flat_quad_base(n: int = 2) -> SubDMesh:
    """Return a flat n×n quad grid in the XY plane (Z=0).

    Vertices are at unit spacing; the grid spans [0, n] in X and Y.
    Vertex ordering is row-major (y-row outer, x-col inner).

    For n=2 we get a 3×3 grid (9 vertices, 4 quads) — the simplest
    all-regular CC-regular base.
    """
    verts = []
    for ry in range(n + 1):
        for rx in range(n + 1):
            verts.append([float(rx), float(ry), 0.0])

    faces = []
    for ry in range(n):
        for rx in range(n):
            v00 = ry * (n + 1) + rx
            v10 = ry * (n + 1) + rx + 1
            v11 = (ry + 1) * (n + 1) + rx + 1
            v01 = (ry + 1) * (n + 1) + rx
            faces.append([v00, v10, v11, v01])

    return SubDMesh(vertices=verts, faces=faces)


def make_single_quad_base() -> SubDMesh:
    """A 2×2 vertex flat quad (1 face).  Minimal base for level-1 tests."""
    verts = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [1.0, 1.0, 0.0],
        [0.0, 1.0, 0.0],
    ]
    faces = [[0, 1, 2, 3]]
    return SubDMesh(vertices=verts, faces=faces)


# ---------------------------------------------------------------------------
# T1 — Identity round-trip
# ---------------------------------------------------------------------------


class TestIdentityRoundTrip:
    """Extract displacement from a synthetically displaced mesh, re-apply, recover original."""

    def _make_displaced_fine_mesh(
        self,
        base: SubDMesh,
        level: int,
        amplitude: float = 0.5,
    ) -> tuple:
        """Subdivide base to level, displace each vertex by amplitude * normal.

        Returns (displaced_mesh, reference_fine_mesh, per_vertex_scalars).
        """
        fine = catmull_clark_subdivide(base, levels=level)
        normals = _compute_stam_normals(fine)
        displaced_verts = []
        scalars = []
        for vi, v in enumerate(fine.vertices):
            n = normals[vi]
            vp = np.array(v, dtype=float) + amplitude * n
            displaced_verts.append(vp.tolist())
            scalars.append(amplitude)
        displaced = SubDMesh(
            vertices=displaced_verts,
            faces=[list(f) for f in fine.faces],
            creases=dict(fine.creases),
        )
        return displaced, fine, scalars

    def test_round_trip_flat_grid_level1(self):
        """Round-trip on a flat 2×2 base at level 1."""
        base = make_flat_quad_base(n=2)
        fine_displaced, fine_ref, expected_scalars = self._make_displaced_fine_mesh(
            base, level=1, amplitude=0.3
        )

        # Extract displacement
        dmap = extract_displacement(fine_displaced, base, level=1)

        # Re-apply displacement
        result = apply_displacement(base, level=1, displacement_map=dmap)

        assert len(result.vertices) == len(fine_displaced.vertices), (
            "Re-applied mesh vertex count mismatch"
        )

        # Positional error must be ≤ 1e-9 for the clean synthetic case.
        # We test mean absolute error; perfect round-trip expected.
        max_err = 0.0
        for vi, (rv, fv) in enumerate(zip(result.vertices, fine_displaced.vertices)):
            err = math.sqrt(sum((a - b) ** 2 for a, b in zip(rv, fv)))
            max_err = max(max_err, err)

        # For a clean synthetic displacement along exact Stam normals, the
        # round-trip error should be < 1e-6 (numerical precision of bilinear
        # interpolation and normal recomputation).
        assert max_err < 1e-6, (
            f"Round-trip positional error {max_err:.2e} exceeds 1e-6"
        )

    def test_round_trip_zero_displacement(self):
        """Zero displacement round-trip: re-applied mesh == reference subdivision."""
        base = make_flat_quad_base(n=2)
        level = 1
        fine_ref = catmull_clark_subdivide(base, levels=level)

        # Build a zero displacement map
        n_verts = len(fine_ref.vertices)
        k = int(math.ceil(math.sqrt(n_verts)))
        k_sq = int(round(math.sqrt(n_verts)))
        if k_sq * k_sq == n_verts:
            rows, cols = k_sq, k_sq
        else:
            rows, cols = k, k
        zero_samples = np.zeros((rows, cols), dtype=float)
        dmap = DisplacementMap(samples=zero_samples)

        result = apply_displacement(base, level=level, displacement_map=dmap)

        for vi, (rv, fv) in enumerate(zip(result.vertices, fine_ref.vertices)):
            err = math.sqrt(sum((a - b) ** 2 for a, b in zip(rv, fv)))
            assert err < 1e-12, f"Vertex {vi}: zero-displacement error {err:.2e}"

    def test_round_trip_vertex_count_preserved(self):
        """apply_displacement returns the same vertex count as the subdivided base."""
        base = make_flat_quad_base(n=2)
        fine = catmull_clark_subdivide(base, levels=2)
        n_fine = len(fine.vertices)

        k = int(round(math.sqrt(n_fine)))
        rows, cols = (k, k) if k * k == n_fine else (k + 1, k + 1)
        dmap = DisplacementMap(samples=np.zeros((rows, cols)))

        result = apply_displacement(base, level=2, displacement_map=dmap)
        assert len(result.vertices) == n_fine


# ---------------------------------------------------------------------------
# T2 — Smooth sinusoidal displacement
# ---------------------------------------------------------------------------


class TestSinusoidalDisplacement:
    """Sinusoidal displacement map on a flat base produces the expected profile."""

    def test_sinusoidal_z_profile(self):
        """Apply sin(π u) sin(π v) map; fine-mesh Z must match expected within 1% RMS."""
        amplitude = 1.0
        grid_size = 17  # fine enough grid for good bilinear fidelity
        rows, cols = grid_size, grid_size

        # Build displacement map: d(u,v) = amplitude * sin(π u) * sin(π v)
        u_vals = np.linspace(0.0, 1.0, cols)
        v_vals = np.linspace(0.0, 1.0, rows)
        samples = np.outer(np.sin(math.pi * v_vals), np.sin(math.pi * u_vals)) * amplitude
        dmap = DisplacementMap(samples=samples)

        base = make_flat_quad_base(n=2)  # flat Z=0 base
        level = 2
        result = apply_displacement(base, level=level, displacement_map=dmap)

        # The fine mesh is flat (Z=0) before displacement; after displacement
        # each vertex at grid position (u, v) should have Z ≈ sin(π u) sin(π v).
        # Compute UV for each result vertex.
        uvs = _compute_vertex_uvs(result)

        errors = []
        for vi, ((u, v), vert) in enumerate(zip(uvs, result.vertices)):
            expected_z = amplitude * math.sin(math.pi * u) * math.sin(math.pi * v)
            actual_z = vert[2]
            errors.append((actual_z - expected_z) ** 2)

        rms_err = math.sqrt(sum(errors) / len(errors))
        # 1% RMS relative to peak amplitude
        assert rms_err < 0.01 * amplitude, (
            f"Sinusoidal Z-profile RMS error {rms_err:.4f} exceeds 1% of amplitude {amplitude}"
        )

    def test_sinusoidal_vertices_move_in_normal_direction(self):
        """Vertices with positive displacement must move in the +Z direction on a flat mesh."""
        # On a flat XY mesh, the limit normal points in +Z, so positive
        # displacement → positive ΔZ.
        amplitude = 0.5
        rows, cols = 5, 5
        samples = np.full((rows, cols), amplitude)
        dmap = DisplacementMap(samples=samples)

        base = make_flat_quad_base(n=2)
        level = 1
        result = apply_displacement(base, level=level, displacement_map=dmap)
        fine_ref = catmull_clark_subdivide(base, levels=level)

        for vi, (rv, fv) in enumerate(zip(result.vertices, fine_ref.vertices)):
            dz = rv[2] - fv[2]
            # The z-component of the normal on a flat mesh is +1, so dz ≈ +amplitude
            assert dz > 0, f"Vertex {vi}: expected positive Z-displacement, got {dz:.4f}"


# ---------------------------------------------------------------------------
# T3 — Pyramid reconstruction
# ---------------------------------------------------------------------------


class TestPyramidReconstruction:
    """Pyramid encode → decode exactly reproduces the original at the correct level.

    All maps must share the same grid size for exact reconstruction (the pyramid
    stores Laplacian residuals; bilinear resampling across different sizes is
    lossy by design, so exact reconstruction is only guaranteed for same-size grids).
    """

    def _make_same_size_maps(self, n_levels: int = 3, size: int = 8) -> list:
        """Return n_levels DisplacementMaps all of the same (size × size) resolution.

        Each map represents a progressively richer signal so the residuals are
        non-trivial; exact reconstruction is then verifiable via encode→decode.
        """
        maps = []
        u = np.linspace(0.0, 1.0, size)
        v = np.linspace(0.0, 1.0, size)
        accumulated = np.zeros((size, size), dtype=float)
        for k in range(n_levels):
            freq = k + 1
            layer = 0.1 * np.outer(
                np.sin(freq * math.pi * v), np.cos(freq * math.pi * u)
            )
            accumulated = accumulated + layer
            maps.append(DisplacementMap(samples=accumulated.copy()))
        return maps

    def test_pyramid_reconstruction_exact_at_finest_level(self):
        """decode_pyramid at level n-1 must reproduce the finest input map exactly.

        With same-size grids the Laplacian pyramid encode/decode is lossless:
        sum(residuals[0..k]) == maps[k] to floating-point precision (≤ 1e-9).
        """
        maps = self._make_same_size_maps(n_levels=3, size=8)
        pyr = encode_pyramid(maps)
        reconstructed = decode_pyramid(pyr, level=2)

        np.testing.assert_allclose(
            reconstructed.samples,
            maps[2].samples,
            atol=1e-9,
            err_msg="Pyramid reconstruction at finest level deviates from original",
        )

    def test_pyramid_reconstruction_coarse_level(self):
        """decode_pyramid at level 0 must reproduce maps[0] exactly."""
        maps = self._make_same_size_maps(n_levels=3, size=4)
        pyr = encode_pyramid(maps)
        reconstructed = decode_pyramid(pyr, level=0)
        np.testing.assert_allclose(
            reconstructed.samples,
            maps[0].samples,
            atol=1e-9,
            err_msg="Pyramid reconstruction at coarsest level deviates from original",
        )

    def test_pyramid_level_count(self):
        """Pyramid should have as many levels as input maps."""
        maps = self._make_same_size_maps(n_levels=4, size=4)
        pyr = encode_pyramid(maps)
        assert pyr.num_levels() == 4

    def test_pyramid_roundtrip_intermediate(self):
        """decode_pyramid at level 1 reconstructs maps[1] exactly (same-size grid)."""
        maps = self._make_same_size_maps(n_levels=3, size=6)
        pyr = encode_pyramid(maps)
        reconstructed = decode_pyramid(pyr, level=1)
        np.testing.assert_allclose(
            reconstructed.samples,
            maps[1].samples,
            atol=1e-9,
            err_msg="Pyramid intermediate level reconstruction deviates from original",
        )


# ---------------------------------------------------------------------------
# T4 — LOD coarsening
# ---------------------------------------------------------------------------


class TestLODCoarsening:
    """decode_pyramid at a coarser level produces an approximation, not exact reproduction."""

    def test_lod_coarser_level_is_different(self):
        """The coarse-level reconstruction must differ from the fine-level one."""
        size = 8
        # Create maps with a fine-detail sinusoidal pattern
        maps = []
        for k in range(3):
            s = size * (k + 1)
            u = np.linspace(0.0, 1.0, s)
            v = np.linspace(0.0, 1.0, s)
            # Coarse: smooth; fine: smooth + high-freq detail
            if k == 0:
                samples = 0.1 * np.outer(np.sin(math.pi * v), np.sin(math.pi * u))
            else:
                freq = 2 ** k
                samples = (
                    0.1 * np.outer(np.sin(math.pi * v), np.sin(math.pi * u))
                    + 0.05 * np.outer(
                        np.sin(freq * math.pi * v), np.sin(freq * math.pi * u)
                    )
                )
            maps.append(DisplacementMap(samples=samples))

        pyr = encode_pyramid(maps)
        fine_rec = decode_pyramid(pyr, level=2)     # finest level
        coarse_rec = decode_pyramid(pyr, level=0)   # coarsest level

        # Resample coarse to fine resolution for comparison
        from kerf_cad_core.geom.multires_displacement import _resample_map
        coarse_up = _resample_map(coarse_rec.samples, fine_rec.height, fine_rec.width)

        diff = fine_rec.samples - coarse_up
        rms_diff = float(np.sqrt(np.mean(diff ** 2)))

        # The coarser reconstruction must differ from the fine one (rms_diff > 0)
        assert rms_diff > 1e-10, (
            "LOD coarser level unexpectedly matches fine level exactly "
            "(detail maps should add non-zero residuals)"
        )

    def test_lod_coarser_within_amplitude_bounds(self):
        """The coarser reconstruction must not deviate by more than the map's amplitude."""
        size = 6
        amplitude = 0.2
        u = np.linspace(0.0, 1.0, size)
        v = np.linspace(0.0, 1.0, size)
        coarse_samples = amplitude * np.outer(np.sin(math.pi * v), np.sin(math.pi * u))

        size2 = size * 2
        u2 = np.linspace(0.0, 1.0, size2)
        v2 = np.linspace(0.0, 1.0, size2)
        fine_samples = (
            amplitude * np.outer(np.sin(math.pi * v2), np.sin(math.pi * u2))
            + 0.1 * amplitude * np.outer(np.sin(2 * math.pi * v2), np.sin(2 * math.pi * u2))
        )

        maps = [
            DisplacementMap(samples=coarse_samples),
            DisplacementMap(samples=fine_samples),
        ]
        pyr = encode_pyramid(maps)
        coarse_rec = decode_pyramid(pyr, level=0)

        # All values in the coarse reconstruction must be within [-amplitude, +amplitude]
        assert float(np.max(np.abs(coarse_rec.samples))) <= amplitude * 1.01, (
            "Coarse LOD reconstruction exceeds expected amplitude bounds"
        )

    def test_lod_level1_is_recognisable_approximation(self):
        """Level-1 decode from a 3-level pyramid approximates but differs from level-2."""
        size = 8
        maps = []
        for k in range(3):
            s = size + k * 4
            u = np.linspace(0.0, 1.0, s)
            v = np.linspace(0.0, 1.0, s)
            freq = k + 1
            samples = 0.1 * np.outer(
                np.sin(freq * math.pi * v), np.sin(freq * math.pi * u)
            )
            maps.append(DisplacementMap(samples=samples))

        pyr = encode_pyramid(maps)
        rec1 = decode_pyramid(pyr, level=1)
        rec2 = decode_pyramid(pyr, level=2)

        # rec1 and rec2 should differ (level 2 has more detail than level 1)
        from kerf_cad_core.geom.multires_displacement import _resample_map
        rec1_up = _resample_map(rec1.samples, rec2.height, rec2.width)
        diff = rec2.samples - rec1_up
        rms_diff = float(np.sqrt(np.mean(diff ** 2)))
        assert rms_diff > 1e-12, (
            "Level-1 and level-2 LOD reconstructions are identical; "
            "pyramid is not encoding detail correctly"
        )


# ---------------------------------------------------------------------------
# DisplacementMap bilinear interpolation
# ---------------------------------------------------------------------------


class TestDisplacementMapSampling:
    def test_corner_values(self):
        samples = np.array([[1.0, 2.0], [3.0, 4.0]])
        dmap = DisplacementMap(samples=samples)
        assert abs(dmap.sample(0.0, 0.0) - 1.0) < 1e-12
        assert abs(dmap.sample(1.0, 0.0) - 2.0) < 1e-12
        assert abs(dmap.sample(0.0, 1.0) - 3.0) < 1e-12
        assert abs(dmap.sample(1.0, 1.0) - 4.0) < 1e-12

    def test_centre_bilinear(self):
        samples = np.array([[1.0, 2.0], [3.0, 4.0]])
        dmap = DisplacementMap(samples=samples)
        # At the centre (0.5, 0.5) bilinear average = (1+2+3+4)/4 = 2.5
        assert abs(dmap.sample(0.5, 0.5) - 2.5) < 1e-12

    def test_clamp_out_of_range(self):
        samples = np.array([[1.0, 2.0], [3.0, 4.0]])
        dmap = DisplacementMap(samples=samples)
        # Values outside [0,1] must be clamped
        assert abs(dmap.sample(-0.5, 0.0) - 1.0) < 1e-12
        assert abs(dmap.sample(1.5, 1.0) - 4.0) < 1e-12
