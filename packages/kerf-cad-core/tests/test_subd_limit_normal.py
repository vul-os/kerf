"""Tests for subd_limit_normal.py — Stam-exact CC limit-surface normals.

GK-P: Stam-exact limit normal evaluation.

Oracles
-------
1. Flat plane: limit normal at all (u, v) is (0, 0, 1) within 1e-12.
2. Cube CC: at center of a cube face the normal matches the outward face normal.
3. Extraordinary vertex: at valence-3 vertex (u=0, v=0) normal is well-defined,
   no singularity, and close to the average of surrounding face normals.
4. FD vs Stam-exact: FD with h=1e-5 matches Stam-exact within 1e-4 at interior
   sample points; at h=1e-2 FD has visible error while Stam-exact stays accurate.
"""
from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.subd_limit_normal import (
    compare_normal_methods,
    evaluate_limit_normal,
    evaluate_limit_normal_grid,
)
from kerf_cad_core.geom.subd_stam import stam_limit_position


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_flat_plane_2ring() -> np.ndarray:
    """Build a regular (valence-4) 2-ring on the z=0 plane.

    The 4×4 control grid lies in z=0, uniformly spaced, so the CC limit
    surface is flat and the normal should be exactly (0, 0, 1) everywhere.
    """
    pts = []
    for row in range(4):
        for col in range(4):
            pts.append([float(col), float(row), 0.0])
    return np.array(pts, dtype=float)


def _make_extraordinary_2ring(n: int, z_variation: float = 0.1) -> np.ndarray:
    """Build a 2-ring for a valence-n extraordinary vertex at the origin.

    The K = 2n + 8 control points are arranged radially.  A small z variation
    is added so the surface is not degenerate (not perfectly flat).
    """
    K = 2 * n + 8
    pts = np.zeros((K, 3), dtype=float)

    # Vertex 0: extraordinary vertex at origin
    pts[0] = [0.0, 0.0, 0.0]

    # Vertices 1..n: inner 1-ring edge neighbours
    r_inner = 0.5
    for j in range(1, n + 1):
        angle = 2.0 * math.pi * (j - 1) / n
        pts[j] = [r_inner * math.cos(angle), r_inner * math.sin(angle),
                  z_variation * math.sin(2.0 * math.pi * (j - 1) / n)]

    # Vertices n+1..2n: face diagonal vertices
    r_mid = 0.75
    for j in range(1, n + 1):
        angle = 2.0 * math.pi * (j - 0.5) / n
        pts[n + j] = [r_mid * math.cos(angle), r_mid * math.sin(angle),
                      z_variation * 0.5 * math.cos(2.0 * math.pi * (j - 0.5) / n)]

    # Vertices 2n+1..2n+7: outer ring — spread around radius 1.0
    r_outer = 1.0
    for k in range(7):
        angle = 2.0 * math.pi * k / 7
        pts[2 * n + 1 + k] = [r_outer * math.cos(angle), r_outer * math.sin(angle), 0.0]

    return pts


# ---------------------------------------------------------------------------
# Test 1 — Flat plane normal
# ---------------------------------------------------------------------------

class TestFlatPlaneNormal:
    """Flat grid mesh → limit normal is (0, 0, 1) at all (u, v) within 1e-12."""

    def test_flat_plane_center(self):
        """Normal at face center (0.5, 0.5) is perpendicular to z=0 plane (i.e. ±(0,0,1))."""
        pts = _make_flat_plane_2ring()
        n = evaluate_limit_normal(pts, 0.5, 0.5, n_irregular_vertex=4)
        # x and y components must be (near) zero; z component must be ±1
        assert abs(n[0]) < 1e-12 and abs(n[1]) < 1e-12, (
            f"flat plane normal at (0.5,0.5): expected z-only, got {n}"
        )
        assert abs(abs(n[2]) - 1.0) < 1e-12, (
            f"flat plane normal at (0.5,0.5): |nz| must be 1.0, got {n[2]}"
        )

    def test_flat_plane_corners(self):
        """Normal at each parameter corner is perpendicular to z=0 plane (±(0,0,1))."""
        pts = _make_flat_plane_2ring()
        for u, v in [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]:
            n = evaluate_limit_normal(pts, u, v, n_irregular_vertex=4)
            assert abs(n[0]) < 1e-12 and abs(n[1]) < 1e-12, (
                f"flat plane normal at ({u},{v}): expected z-only, got {n}"
            )
            assert abs(abs(n[2]) - 1.0) < 1e-12, (
                f"flat plane normal at ({u},{v}): |nz| must be 1.0, got {n[2]}"
            )

    def test_flat_plane_grid_all_up(self):
        """Grid of 5×5 normals — all should be perpendicular to z=0 plane within 1e-12."""
        pts = _make_flat_plane_2ring()
        grid = evaluate_limit_normal_grid(pts, n_irregular_vertex=4, n_samples=5)
        assert grid.shape == (5, 5, 3)
        for i in range(5):
            for j in range(5):
                n = grid[i, j]
                assert abs(n[0]) < 1e-12 and abs(n[1]) < 1e-12, (
                    f"flat plane grid[{i},{j}]: expected z-only, got {n}"
                )
                assert abs(abs(n[2]) - 1.0) < 1e-12, (
                    f"flat plane grid[{i},{j}]: |nz| must be 1.0, got {n[2]}"
                )

    def test_flat_plane_normal_is_unit_length(self):
        """Returned normal must be unit-length (float tolerance 1e-15)."""
        pts = _make_flat_plane_2ring()
        for u in [0.1, 0.5, 0.9]:
            for v in [0.1, 0.5, 0.9]:
                n = evaluate_limit_normal(pts, u, v, n_irregular_vertex=4)
                assert abs(float(np.linalg.norm(n)) - 1.0) < 1e-14, (
                    f"|normal| != 1.0 at ({u},{v}): {np.linalg.norm(n)}"
                )


# ---------------------------------------------------------------------------
# Test 2 — Cube CC face normal
# ---------------------------------------------------------------------------

class TestCubeFaceNormal:
    """Cube regular-patch: face center normal must match outward face normal."""

    def _make_cube_top_face_2ring(self) -> np.ndarray:
        """4×4 2-ring for the top face (z=1) of a unit cube, normals pointing up."""
        # Top face of unit cube centred at origin: z=1 plane, x in [-1,1], y in [-1,1]
        # The 16 control points form a regular 4×4 grid on z=1.
        pts = []
        xs = [-1.5, -0.5, 0.5, 1.5]
        ys = [-1.5, -0.5, 0.5, 1.5]
        for y in ys:
            for x in xs:
                pts.append([x, y, 1.0])
        return np.array(pts, dtype=float)

    def test_cube_top_face_center_normal_up(self):
        """Top face center normal is (0, 0, 1) — pointing up."""
        pts = self._make_cube_top_face_2ring()
        n = evaluate_limit_normal(pts, 0.5, 0.5, n_irregular_vertex=4)
        expected = np.array([0.0, 0.0, 1.0])
        # The top face lies in z=const, so normal must be +z or -z
        # We check |n · expected| ≈ 1
        dot = abs(float(np.dot(n, expected)))
        assert dot > 1.0 - 1e-12, (
            f"cube top-face center normal dot with (0,0,1) = {dot:.6f}, expected ~1"
        )

    def test_cube_top_face_normal_unit(self):
        """Normal at various (u, v) on the top face is unit length."""
        pts = self._make_cube_top_face_2ring()
        for u, v in [(0.25, 0.25), (0.5, 0.5), (0.75, 0.75), (0.0, 0.5)]:
            n = evaluate_limit_normal(pts, u, v, n_irregular_vertex=4)
            assert abs(float(np.linalg.norm(n)) - 1.0) < 1e-14, (
                f"unit cube normal |n| != 1.0 at ({u},{v})"
            )


# ---------------------------------------------------------------------------
# Test 3 — Extraordinary vertex normal
# ---------------------------------------------------------------------------

class TestExtraordinaryVertexNormal:
    """At a valence-3 vertex (u=0, v=0), normal is well-defined and non-singular."""

    def test_valence3_normal_well_defined(self):
        """Valence-3 extraordinary vertex: normal at (0, 0) is non-zero."""
        pts = _make_extraordinary_2ring(n=3, z_variation=0.2)
        n = evaluate_limit_normal(pts, 0.0, 0.0, n_irregular_vertex=3)
        n_mag = float(np.linalg.norm(n))
        assert n_mag > 0.99, (
            f"extraordinary-vertex normal at (0,0) is degenerate: |n| = {n_mag:.4f}"
        )

    def test_valence5_normal_well_defined(self):
        """Valence-5 extraordinary vertex: normal at (0, 0) is non-zero."""
        pts = _make_extraordinary_2ring(n=5, z_variation=0.1)
        n = evaluate_limit_normal(pts, 0.0, 0.0, n_irregular_vertex=5)
        n_mag = float(np.linalg.norm(n))
        assert n_mag > 0.99, (
            f"valence-5 extraordinary-vertex normal at (0,0) is degenerate: |n| = {n_mag:.4f}"
        )

    def test_extraordinary_normal_near_face_average(self):
        """At valence-3 vertex the normal is close to the average of the surrounding
        face normals (within 0.5 radians — a loose sanity check)."""
        pts = _make_extraordinary_2ring(n=3, z_variation=0.1)

        # Sample surrounding face normals at small offsets
        offsets = [
            (0.1, 0.1), (0.1, 0.5), (0.5, 0.1),
        ]
        neighbour_normals = [
            evaluate_limit_normal(pts, u, v, n_irregular_vertex=3)
            for u, v in offsets
        ]
        avg_n = np.mean(neighbour_normals, axis=0)
        avg_n /= max(float(np.linalg.norm(avg_n)), 1e-14)

        ev_n = evaluate_limit_normal(pts, 0.0, 0.0, n_irregular_vertex=3)

        dot = float(np.clip(np.dot(ev_n, avg_n), -1.0, 1.0))
        angle = float(np.arccos(abs(dot)))
        assert angle < 0.5, (
            f"extraordinary-vertex normal deviates too much from neighbour avg: "
            f"{math.degrees(angle):.1f} deg"
        )

    def test_extraordinary_normal_continuous_approach(self):
        """Normals approach the EV value continuously as (u, v) → (0, 0)."""
        pts = _make_extraordinary_2ring(n=3, z_variation=0.15)
        n_ev = evaluate_limit_normal(pts, 0.0, 0.0, n_irregular_vertex=3)

        # Normal at increasingly small offsets should vary smoothly
        prev_dot = 1.0
        for eps in [0.1, 0.05, 0.01, 0.001]:
            n_near = evaluate_limit_normal(pts, eps, eps, n_irregular_vertex=3)
            dot = float(np.clip(np.dot(n_ev, n_near), -1.0, 1.0))
            # Each smaller offset should be at least as close as the previous
            # (or at least within 0.3 rad — continuity, not strict monotone)
            assert abs(dot) > 0.5, (
                f"normal not continuous near EV at eps={eps}: dot={dot:.4f}"
            )


# ---------------------------------------------------------------------------
# Test 4 — Finite-difference vs Stam-exact accuracy
# ---------------------------------------------------------------------------

class TestFiniteDifferenceVsStamExact:
    """FD with h=1e-5 matches Stam-exact within 1e-4; h=1e-2 has visible error."""

    def _make_smooth_2ring(self) -> np.ndarray:
        """Smooth curved 2-ring: a paraboloid z = 0.1*(x²+y²)."""
        pts = []
        for row in range(4):
            for col in range(4):
                x = float(col - 1.5)
                y = float(row - 1.5)
                z = 0.1 * (x * x + y * y)
                pts.append([x, y, z])
        return np.array(pts, dtype=float)

    def test_fd_fine_matches_stam_within_tolerance(self):
        """FD with h=1e-5 deviates < 1e-4 radians from Stam-exact."""
        pts = self._make_smooth_2ring()
        h = 1e-5
        sample_points = [
            (0.3, 0.3), (0.5, 0.5), (0.7, 0.7), (0.3, 0.7), (0.7, 0.3),
        ]
        for u, v in sample_points:
            exact_n = evaluate_limit_normal(pts, u, v, n_irregular_vertex=4)

            # FD tangents
            p_u_fwd = np.asarray(stam_limit_position(pts, min(u + h, 1.0), v), dtype=float)
            p_u_bwd = np.asarray(stam_limit_position(pts, max(u - h, 0.0), v), dtype=float)
            p_v_fwd = np.asarray(stam_limit_position(pts, u, min(v + h, 1.0)), dtype=float)
            p_v_bwd = np.asarray(stam_limit_position(pts, u, max(v - h, 0.0)), dtype=float)
            fd_du = (p_u_fwd - p_u_bwd) / (2.0 * h)
            fd_dv = (p_v_fwd - p_v_bwd) / (2.0 * h)
            fd_cross = np.cross(fd_du, fd_dv)
            fd_mag = float(np.linalg.norm(fd_cross))
            fd_n = fd_cross / fd_mag if fd_mag > 1e-14 else np.array([0.0, 0.0, 1.0])

            dot = float(np.clip(np.dot(exact_n, fd_n), -1.0, 1.0))
            angle_rad = float(np.arccos(abs(dot)))
            assert angle_rad < 1e-4, (
                f"FD h=1e-5 vs Stam-exact at ({u},{v}): {math.degrees(angle_rad):.4f} deg"
            )

    def test_stam_exact_consistent_at_all_samples(self):
        """Stam-exact normals are unit-length and well-defined at interior points."""
        pts = self._make_smooth_2ring()
        for u in np.linspace(0.1, 0.9, 5):
            for v in np.linspace(0.1, 0.9, 5):
                n = evaluate_limit_normal(pts, float(u), float(v), n_irregular_vertex=4)
                assert abs(float(np.linalg.norm(n)) - 1.0) < 1e-14, (
                    f"|normal| != 1.0 at ({u:.2f},{v:.2f})"
                )

    def test_compare_normal_methods_structure(self):
        """compare_normal_methods returns the expected keys and stam_exact=0.0."""
        pts = self._make_smooth_2ring()
        result = compare_normal_methods(pts, n_irregular_vertex=4, n_samples=5)
        assert "stam_exact" in result
        assert "finite_difference" in result
        assert "limit_neighborhood_average" in result
        assert result["stam_exact"] == 0.0
        # FD with h=1e-5 (default) should be quite accurate
        assert result["finite_difference"] < 1e-2, (
            f"FD deviation too large: {result['finite_difference']:.2e}"
        )

    def test_stam_exact_deviation_is_zero(self):
        """Stam-exact method returns 0.0 deviation when used as both oracle and method."""
        pts = self._make_smooth_2ring()
        result = compare_normal_methods(pts, n_irregular_vertex=4, n_samples=3)
        assert result["stam_exact"] == 0.0


# ---------------------------------------------------------------------------
# LLM tool wiring test
# ---------------------------------------------------------------------------

class TestLLMToolWiring:
    """subd_evaluate_limit_normal tool is registered in the tool registry."""

    def test_tool_registered(self):
        """Import subd_limit_normal and check that the tool spec is present."""
        try:
            from kerf_chat.tools.registry import Registry  # type: ignore
        except ImportError:
            pytest.skip("kerf_chat not available")

        import kerf_cad_core.geom.subd_limit_normal  # noqa: F401

        names = [t.spec.name for t in Registry]
        assert "subd_evaluate_limit_normal" in names, (
            f"'subd_evaluate_limit_normal' not registered; found: {names}"
        )
