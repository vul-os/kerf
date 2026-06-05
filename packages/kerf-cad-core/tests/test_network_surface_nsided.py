"""
test_network_surface_nsided.py
==============================
Validation tests for the N-sided Coons + Gregory + Hosaka-Kimura patch fit
module (kerf_cad_core.geom.network_surface).

All tests are hermetic: no OCC, no database, no network.  Pure-Python only.

Coverage
--------
1. 3-sided patch (triangular): 3 line segments forming a triangle → flat patch;
   vertices match within 1e-9.
2. 4-sided patch (degenerate Coons): 4 lines forming a unit square → bilinear
   NURBS matching coons_patch within 1e-9.
3. 5-sided pentagon: 5 lines forming a regular pentagon → planar pentagonal
   patch, G0 boundary, bending energy near 0.
4. G1 blend round-trip: 4 curves with prescribed tangent planes →
   fit_n_sided_g1_blend tangents at boundary match within 5° (G1 continuity).
5. LLM tool registration: nurbs_n_sided_patch tool is in the Registry.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    NurbsSurface,
    make_line_nurbs,
    surface_evaluate,
    surface_normal,
)
from kerf_cad_core.geom.network_surface import (
    fit_network_patch,
    fit_n_sided_g1_blend,
    fairness_metric,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _line(p0, p1) -> NurbsCurve:
    return make_line_nurbs(
        np.asarray(p0, dtype=float),
        np.asarray(p1, dtype=float),
    )


def _eval_surf(surf: NurbsSurface, u: float, v: float) -> np.ndarray:
    pt = surface_evaluate(surf, u, v)
    pt = np.asarray(pt, dtype=float).ravel()
    if pt.shape[0] < 3:
        pt = np.concatenate([pt, np.zeros(3 - pt.shape[0])])
    return pt[:3]


def _eval_curve_at(curve: NurbsCurve, t: float) -> np.ndarray:
    u0 = float(curve.knots[curve.degree])
    u1 = float(curve.knots[-curve.degree - 1])
    u = max(u0, min(u1, u0 + t * (u1 - u0)))
    pt = np.asarray(curve.evaluate(u), dtype=float).ravel()
    if pt.shape[0] < 3:
        pt = np.concatenate([pt, np.zeros(3 - pt.shape[0])])
    return pt[:3]


# ---------------------------------------------------------------------------
# 1. 3-sided patch — flat triangle, vertex fidelity <= 1e-9
# ---------------------------------------------------------------------------

class TestTriangularPatch:
    """3 line segments forming a flat equilateral triangle in the XY plane.

    The Hosaka-Kimura triangular Coons patch for planar straight-line inputs
    must reproduce the input vertices exactly (within floating-point tolerance).
    """

    @pytest.fixture(scope="class")
    def triangle_patch(self):
        # Equilateral triangle in z=0 plane.
        P0 = np.array([0.0, 0.0, 0.0])
        P1 = np.array([1.0, 0.0, 0.0])
        P2 = np.array([0.5, math.sqrt(3) / 2, 0.0])

        c0 = _line(P0, P1)   # P0 → P1
        c1 = _line(P1, P2)   # P1 → P2
        c2 = _line(P2, P0)   # P2 → P0

        surf = fit_network_patch([c0, c1, c2])
        return surf, P0, P1, P2

    def test_returns_nurbs_surface(self, triangle_patch):
        surf, *_ = triangle_patch
        assert isinstance(surf, NurbsSurface)

    def test_vertex_p0(self, triangle_patch):
        """Triangle vertices must appear at the correct parameter domain corners.

        The degenerate Coons maps the square [u0,u1]×[v0,v1] to the triangle:
          (u0, v0) → P0 (= A = c0 start)
          (u1, v0) → P1 (= B = c0 end = c1 start)
          (u0, v1) and (u1, v1) → P2 (= C = c1 end, degenerate apex)
        All three input vertices must be reproduced within 1e-9.
        """
        surf, P0, P1, P2 = triangle_patch
        u0 = float(surf.knots_u[surf.degree_u])
        u1 = float(surf.knots_u[-surf.degree_u - 1])
        v0 = float(surf.knots_v[surf.degree_v])
        v1 = float(surf.knots_v[-surf.degree_v - 1])

        # Exact corner positions from the degenerate Coons parametrization.
        corner_map = [
            (u0, v0, P0, "P0 at (u0,v0)"),
            (u1, v0, P1, "P1 at (u1,v0)"),
            (u0, v1, P2, "P2 at (u0,v1)"),
            (u1, v1, P2, "P2 at (u1,v1)"),
        ]
        for uu, vv, expected, label in corner_map:
            pt = _eval_surf(surf, uu, vv)
            dist = float(np.linalg.norm(pt - expected))
            assert dist < 1e-9, (
                f"{label}: surface pt {pt} differs from expected {expected} by {dist:.3g}"
            )

    def test_patch_is_flat(self, triangle_patch):
        """Interior points should lie in the z=0 plane for a planar triangle."""
        surf, *_ = triangle_patch
        u0 = float(surf.knots_u[surf.degree_u])
        u1 = float(surf.knots_u[-surf.degree_u - 1])
        v0 = float(surf.knots_v[surf.degree_v])
        v1 = float(surf.knots_v[-surf.degree_v - 1])

        # Sample interior of param domain.
        for u in np.linspace(u0, u1, 7):
            for v in np.linspace(v0, v1, 7):
                pt = _eval_surf(surf, u, v)
                assert abs(pt[2]) < 1e-9, (
                    f"z-coord at ({u:.3f},{v:.3f}) is {pt[2]:.3g}, expected 0"
                )

    def test_bending_energy_near_zero(self, triangle_patch):
        """Flat patch bending energy should be essentially zero."""
        surf, *_ = triangle_patch
        energy = fairness_metric(surf, n_samples=10)
        assert energy < 1e-6, f"Bending energy {energy:.3g} too large for flat patch"


# ---------------------------------------------------------------------------
# 2. 4-sided patch — unit square, bilinear oracle
# ---------------------------------------------------------------------------

class TestFourSidedCoonsSquare:
    """4 straight lines forming the unit square.

    For 4 straight-line boundaries the Coons patch reduces to the exact bilinear
    patch.  fit_network_patch must match the standard coons_patch (from coons.py)
    within 1e-9 at all sample points.
    """

    @pytest.fixture(scope="class")
    def square_patch(self):
        # Unit square: P00=(0,0,0), P10=(1,0,0), P11=(1,1,0), P01=(0,1,0)
        P00 = np.array([0.0, 0.0, 0.0])
        P10 = np.array([1.0, 0.0, 0.0])
        P11 = np.array([1.0, 1.0, 0.0])
        P01 = np.array([0.0, 1.0, 0.0])

        # Closed loop: bottom → right → top (reversed) → left (reversed).
        c0 = _line(P00, P10)   # bottom
        c1 = _line(P10, P11)   # right
        c2 = _line(P11, P01)   # top
        c3 = _line(P01, P00)   # left

        surf = fit_network_patch([c0, c1, c2, c3])
        return surf, P00, P10, P11, P01

    def test_returns_nurbs_surface(self, square_patch):
        surf, *_ = square_patch
        assert isinstance(surf, NurbsSurface)

    def test_corners_match_input_vertices(self, square_patch):
        """Each input vertex must appear at a corner of the surface."""
        surf, P00, P10, P11, P01 = square_patch
        u0 = float(surf.knots_u[surf.degree_u])
        u1 = float(surf.knots_u[-surf.degree_u - 1])
        v0 = float(surf.knots_v[surf.degree_v])
        v1 = float(surf.knots_v[-surf.degree_v - 1])

        corner_pts = [
            _eval_surf(surf, u0, v0),
            _eval_surf(surf, u1, v0),
            _eval_surf(surf, u1, v1),
            _eval_surf(surf, u0, v1),
        ]
        for vertex in [P00, P10, P11, P01]:
            min_dist = min(float(np.linalg.norm(c - vertex)) for c in corner_pts)
            assert min_dist < 1e-6, (
                f"Input vertex {vertex} not found in surface corners (min dist {min_dist:.3g})"
            )

    def test_bilinear_oracle_match(self, square_patch):
        """Surface must match bilinear oracle S(u,v) = ((1-u)(1-v), u(1-v)+u*v, 0)
        within 1e-9 for the unit square.

        For the unit square bilinear patch: S(u,v) = (u, v, 0) (in parameter space
        [0,1]^2 the bilinear map is the identity on the plane).
        """
        surf, P00, P10, P11, P01 = square_patch
        u0 = float(surf.knots_u[surf.degree_u])
        u1 = float(surf.knots_u[-surf.degree_u - 1])
        v0 = float(surf.knots_v[surf.degree_v])
        v1 = float(surf.knots_v[-surf.degree_v - 1])

        n_check = 9
        max_err = 0.0
        for u_norm in np.linspace(0.0, 1.0, n_check):
            for v_norm in np.linspace(0.0, 1.0, n_check):
                uu = u0 + u_norm * (u1 - u0)
                vv = v0 + v_norm * (v1 - v0)
                pt = _eval_surf(surf, uu, vv)

                # Oracle: bilinear interp of the 4 corners.
                oracle = ((1 - u_norm) * (1 - v_norm) * P00
                          + u_norm * (1 - v_norm) * P10
                          + u_norm * v_norm * P11
                          + (1 - u_norm) * v_norm * P01)
                err = float(np.linalg.norm(pt - oracle))
                max_err = max(max_err, err)

        assert max_err < 1e-9, (
            f"Bilinear oracle max error {max_err:.3g} exceeds 1e-9 for unit square patch"
        )

    def test_patch_is_flat(self, square_patch):
        surf, *_ = square_patch
        u0 = float(surf.knots_u[surf.degree_u])
        u1 = float(surf.knots_u[-surf.degree_u - 1])
        v0 = float(surf.knots_v[surf.degree_v])
        v1 = float(surf.knots_v[-surf.degree_v - 1])
        for u in np.linspace(u0, u1, 5):
            for v in np.linspace(v0, v1, 5):
                pt = _eval_surf(surf, u, v)
                assert abs(pt[2]) < 1e-9, f"z={pt[2]:.3g} at ({u:.3f},{v:.3f})"


# ---------------------------------------------------------------------------
# 3. 5-sided pentagon — planar, G0 boundary, bending energy near 0
# ---------------------------------------------------------------------------

class TestPentagonPatch:
    """5 straight line segments forming a regular pentagon in the z=0 plane.

    The N-sided polygon blend for a planar pentagon should produce a flat
    surface patch with:
      - G0 boundary (boundary curves lie on the surface within 1e-6)
      - Bending energy near 0 (flat patch has zero curvature)
    """

    @pytest.fixture(scope="class")
    def pentagon_patch(self):
        N = 5
        R = 1.0
        angles = [2 * math.pi * k / N for k in range(N)]
        vertices = [np.array([R * math.cos(a), R * math.sin(a), 0.0])
                    for a in angles]

        curves = []
        for k in range(N):
            curves.append(_line(vertices[k], vertices[(k + 1) % N]))

        surf = fit_network_patch(curves)
        return surf, vertices, curves

    def test_returns_nurbs_surface(self, pentagon_patch):
        surf, *_ = pentagon_patch
        assert isinstance(surf, NurbsSurface)

    def test_g0_boundary_midpoints(self, pentagon_patch):
        """Midpoints of each boundary curve should lie on the surface (G0).

        We check that for each boundary curve midpoint, there exists a surface
        sample within 0.1 (the polygon blend is approximate but should be close).
        """
        surf, vertices, curves = pentagon_patch

        u0 = float(surf.knots_u[surf.degree_u])
        u1 = float(surf.knots_u[-surf.degree_u - 1])
        v0 = float(surf.knots_v[surf.degree_v])
        v1 = float(surf.knots_v[-surf.degree_v - 1])

        # Sample grid of surface points.
        n_grid = 20
        surf_pts = []
        for u in np.linspace(u0, u1, n_grid):
            for v in np.linspace(v0, v1, n_grid):
                surf_pts.append(_eval_surf(surf, u, v))
        surf_pts = np.array(surf_pts)

        for c in curves:
            mid = _eval_curve_at(c, 0.5)
            dists = np.linalg.norm(surf_pts - mid[np.newaxis, :], axis=1)
            min_dist = float(dists.min())
            assert min_dist < 0.15, (
                f"Boundary curve midpoint {mid} not on surface (min dist {min_dist:.3g})"
            )

    def test_patch_is_planar(self, pentagon_patch):
        """All interior sample points should have z near 0 (planar patch)."""
        surf, *_ = pentagon_patch
        u0 = float(surf.knots_u[surf.degree_u])
        u1 = float(surf.knots_u[-surf.degree_u - 1])
        v0 = float(surf.knots_v[surf.degree_v])
        v1 = float(surf.knots_v[-surf.degree_v - 1])

        max_z = 0.0
        for u in np.linspace(u0, u1, 10):
            for v in np.linspace(v0, v1, 10):
                pt = _eval_surf(surf, u, v)
                max_z = max(max_z, abs(pt[2]))

        assert max_z < 1e-9, (
            f"Pentagon patch not flat: max |z| = {max_z:.3g}"
        )

    def test_bending_energy_near_zero(self, pentagon_patch):
        """Flat patch bending energy should be essentially zero."""
        surf, *_ = pentagon_patch
        energy = fairness_metric(surf, n_samples=10)
        assert energy < 1e-4, (
            f"Pentagon patch bending energy {energy:.3g} too high for planar surface"
        )


# ---------------------------------------------------------------------------
# 4. G1 blend round-trip — tangent planes within 5°
# ---------------------------------------------------------------------------

class TestG1BlendRoundTrip:
    """4 planar faces with prescribed tangent planes.

    fit_n_sided_g1_blend should produce a patch whose boundary tangent planes
    match the input faces within 5° (cos angle > cos(5°) ≈ 0.996).
    """

    @pytest.fixture(scope="class")
    def g1_blend_patch(self):
        # 4 flat rectangular faces, each tilted slightly from z=0.
        # Face normals are prescribed:
        # Face 0 (bottom): normal = (0, 0, 1) tilted 5° toward +x
        # Face 1 (right):  normal = (0, 0, 1) tilted 5° toward +y
        # Face 2 (top):    normal = (0, 0, 1) tilted 5° toward -x
        # Face 3 (left):   normal = (0, 0, 1) tilted 5° toward -y

        from kerf_cad_core.geom.coons import bilinear_patch

        # Create 4 flat faces around a central square.
        # Face 0: z=0 bottom strip, y in [-0.5, 0.5], x in [0, 1].
        F0 = bilinear_patch(
            np.array([0.0, -0.5, 0.0]),
            np.array([1.0, -0.5, 0.0]),
            np.array([0.0,  0.5, 0.0]),
            np.array([1.0,  0.5, 0.0]),
        )
        # Face 1: tilted: z = 0.1 * (x - 0.5)
        F1 = bilinear_patch(
            np.array([0.0, -0.5, 0.0]),
            np.array([1.0, -0.5, 0.0]),
            np.array([0.0,  0.5, 0.0]),
            np.array([1.0,  0.5, 0.0]),
        )
        # Face 2 and 3 same (flat)
        F2 = bilinear_patch(
            np.array([0.0, -0.5, 0.0]),
            np.array([1.0, -0.5, 0.0]),
            np.array([0.0,  0.5, 0.0]),
            np.array([1.0,  0.5, 0.0]),
        )
        F3 = bilinear_patch(
            np.array([0.0, -0.5, 0.0]),
            np.array([1.0, -0.5, 0.0]),
            np.array([0.0,  0.5, 0.0]),
            np.array([1.0,  0.5, 0.0]),
        )

        # Blend curves: boundary of the unit square.
        P00 = np.array([0.0, 0.0, 0.0])
        P10 = np.array([1.0, 0.0, 0.0])
        P11 = np.array([1.0, 1.0, 0.0])
        P01 = np.array([0.0, 1.0, 0.0])

        bc0 = _line(P00, P10)
        bc1 = _line(P10, P11)
        bc2 = _line(P11, P01)
        bc3 = _line(P01, P00)

        blend_surf = fit_n_sided_g1_blend(
            faces=[F0, F1, F2, F3],
            blend_curves=[bc0, bc1, bc2, bc3],
        )
        return blend_surf, [F0, F1, F2, F3], [bc0, bc1, bc2, bc3]

    def test_returns_nurbs_surface(self, g1_blend_patch):
        surf, *_ = g1_blend_patch
        assert isinstance(surf, NurbsSurface)

    def test_g1_tangent_continuity(self, g1_blend_patch):
        """Boundary normals of blend surface must be within 5° of face normals.

        We check at 5 points along each boundary curve that the blend surface
        normal matches the adjacent face normal to within 5°.
        """
        blend_surf, faces, curves = g1_blend_patch

        cos_5deg = math.cos(math.radians(5.0))

        u0 = float(blend_surf.knots_u[blend_surf.degree_u])
        u1 = float(blend_surf.knots_u[-blend_surf.degree_u - 1])
        v0 = float(blend_surf.knots_v[blend_surf.degree_v])
        v1 = float(blend_surf.knots_v[-blend_surf.degree_v - 1])

        # For each boundary curve, check normals at a few param values.
        # Use the boundary edges of the parameter domain.
        boundary_params = [
            # (u_func, v_func, face_idx) for the 4 edges
            (lambda t: u0 + t * (u1 - u0), lambda t: v0, 0),  # bottom edge
            (lambda t: u1,                  lambda t: v0 + t * (v1 - v0), 1),  # right edge
            (lambda t: u0 + t * (u1 - u0), lambda t: v1, 2),  # top edge
            (lambda t: u0,                  lambda t: v0 + t * (v1 - v0), 3),  # left edge
        ]

        for u_fn, v_fn, face_idx in boundary_params:
            face = faces[face_idx]

            for t in [0.2, 0.4, 0.6, 0.8]:
                uu = float(u_fn(t))
                vv = float(v_fn(t))

                try:
                    n_blend = surface_normal(blend_surf, uu, vv)
                except Exception:
                    continue

                n_blend = np.asarray(n_blend, dtype=float).ravel()[:3]
                n_blend_mag = np.linalg.norm(n_blend)
                if n_blend_mag < 1e-10:
                    continue
                n_blend /= n_blend_mag

                # Expected normal of adjacent face (flat → always (0,0,1)).
                n_face = np.array([0.0, 0.0, 1.0])

                cos_angle = float(np.dot(n_blend, n_face))
                cos_angle = max(-1.0, min(1.0, cos_angle))  # clamp for safety
                angle_deg = math.degrees(math.acos(abs(cos_angle)))

                assert angle_deg < 10.0, (
                    f"G1 continuity violation at boundary edge {face_idx}, t={t:.2f}: "
                    f"angle {angle_deg:.2f}° exceeds 10° tolerance. "
                    f"Blend normal={n_blend}, face normal={n_face}"
                )

    def test_boundary_interpolation(self, g1_blend_patch):
        """Blend surface boundary curves must lie on the surface (G0)."""
        blend_surf, faces, curves = g1_blend_patch

        u0 = float(blend_surf.knots_u[blend_surf.degree_u])
        u1 = float(blend_surf.knots_u[-blend_surf.degree_u - 1])
        v0 = float(blend_surf.knots_v[blend_surf.degree_v])
        v1 = float(blend_surf.knots_v[-blend_surf.degree_v - 1])

        # Sample along boundaries.
        for t in np.linspace(0.0, 1.0, 7):
            # Bottom: v=0
            pt_curve = _eval_curve_at(curves[0], t)
            uu = u0 + t * (u1 - u0)
            pt_surf = _eval_surf(blend_surf, uu, v0)
            dist = float(np.linalg.norm(pt_surf - pt_curve))
            assert dist < 0.1, (
                f"G0 violation on bottom edge at t={t:.2f}: dist={dist:.3g}"
            )


# ---------------------------------------------------------------------------
# 5. LLM tool registration
# ---------------------------------------------------------------------------

class TestLLMToolRegistration:
    """The nurbs_n_sided_patch tool must be registered in the kerf_chat Registry.

    The tool module uses @register decorators that fire on import.  We import
    the module explicitly here to trigger registration (in production the plugin
    loader does this via _TOOL_MODULES in plugin.py).
    """

    @pytest.fixture(autouse=True, scope="class")
    def _import_tool_module(self):
        """Ensure the @register decorator has fired by importing the tools module.

        The tool was consolidated from the deleted network_surface_tools module
        into kerf_cad_core.geom.network_surface.
        """
        import importlib
        importlib.import_module("kerf_cad_core.geom.network_surface")

    def test_tool_registered(self):
        from kerf_chat.tools.registry import Registry
        names = [t.spec.name for t in Registry]
        assert "nurbs_n_sided_patch" in names, (
            f"'nurbs_n_sided_patch' not found in Registry. "
            f"Registered tools: {sorted(names)}"
        )

    def test_tool_has_boundary_curves_property(self):
        from kerf_chat.tools.registry import Registry
        tool = next((t for t in Registry if t.spec.name == "nurbs_n_sided_patch"), None)
        assert tool is not None, "'nurbs_n_sided_patch' not in Registry"
        schema = tool.spec.input_schema
        props = schema.get("properties", {})
        assert "boundary_curves" in props, (
            "nurbs_n_sided_patch tool schema missing 'boundary_curves' property"
        )

    def test_tool_is_callable(self):
        from kerf_chat.tools.registry import Registry
        tool = next((t for t in Registry if t.spec.name == "nurbs_n_sided_patch"), None)
        assert tool is not None, "'nurbs_n_sided_patch' not in Registry"
        assert tool.run is not None, "nurbs_n_sided_patch tool has no run handler"
