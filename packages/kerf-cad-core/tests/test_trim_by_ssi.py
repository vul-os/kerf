"""
tests/test_trim_by_ssi.py
=========================
GK-40: Exact trim of a Face by an SSI curve — closest-point pullback.

All tests are hermetic: no OCC, no DB, no network.

Oracle: trim of a PLANE by a CYLINDER gives an exact circle boundary loop
        to ≤1e-7 for radius AND centre.

Coverage
--------
 1. trim_face_by_ssi — Plane × CylinderSurface perpendicular → ok
 2. trim_face_by_ssi — result residual_max ≤ 1e-7
 3. trim_face_by_ssi — loop.is_circle = True
 4. trim_face_by_ssi — loop radius matches cylinder radius (oracle: ≤1e-7)
 5. trim_face_by_ssi — loop centre matches expected (oracle: ≤1e-7)
 6. trim_face_by_ssi — face is not None
 7. trim_face_by_ssi — face.surface is the Plane
 8. trim_face_by_ssi — face has exactly 1 loop (keep_side='inside' → disk)
 9. trim_face_by_ssi — outer loop has 1 coedge (seam arc)
10. trim_face_by_ssi — seam vertex lies on the circle (≤ 1e-7)
11. trim_face_by_ssi — arc centre matches loop_centre (≤ 1e-7)
12. trim_face_by_ssi — arc radius matches cylinder radius (≤ 1e-7)
13. trim_face_by_ssi — uv_boundary has samples entries
14. trim_face_by_ssi — uv_boundary points re-evaluate to circle 3-D pts
15. trim_face_by_ssi — keep_side='outside' returns face with 2 loops
16. trim_face_by_ssi — unsupported pair → ok=False + reason has "unsupported-input"
17. trim_face_by_ssi — unsupported pair → face is None
18. trim_face_by_ssi — never raises for any supported/unsupported pair
19. trim_face_by_ssi — varying radii: oracle residual ≤ 1e-7
20. trim_face_by_ssi — non-origin cylinder: loop centre correct to 1e-7
21. SsiTrimResult dataclass field access
22. ssi_trim alias: trim_face_by_ssi importable from geom.__init__
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.brep import CylinderSurface, Plane, SphereSurface
from kerf_cad_core.geom.trim_curve import (
    AnalyticTrimLoop,
    SsiTrimResult,
    trim_face_by_ssi,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _z_plane(z: float = 0.0) -> Plane:
    return Plane(
        origin=np.array([0.0, 0.0, z]),
        x_axis=np.array([1.0, 0.0, 0.0]),
        y_axis=np.array([0.0, 1.0, 0.0]),
    )


def _z_cylinder(cx: float = 0.0, cy: float = 0.0, cz: float = 0.0,
                r: float = 1.0) -> CylinderSurface:
    return CylinderSurface(
        center=np.array([cx, cy, cz]),
        axis=np.array([0.0, 0.0, 1.0]),
        radius=r,
    )


# ---------------------------------------------------------------------------
# 1–14. Core oracle tests: perpendicular Plane × Z-cylinder
# ---------------------------------------------------------------------------

class TestSsiTrimPlaneCylinder:
    """Oracle: plane at z=1 trimmed by Z-cylinder of radius r.
    The boundary loop must be an exact circle of radius r centred at (0,0,1).
    """

    def setup_method(self):
        self.plane = _z_plane(z=1.0)
        self.cyl = _z_cylinder(r=1.0)
        self.result = trim_face_by_ssi(
            self.plane, self.cyl, keep_side="inside", samples=256, tol=1e-7
        )

    # 1. ok
    def test_ok(self):
        assert self.result["ok"] is True, f"reason: {self.result['reason']}"

    # 2. residual_max ≤ 1e-7
    def test_residual_le_1e7(self):
        assert self.result["residual_max"] <= 1e-7, (
            f"residual {self.result['residual_max']:.3e} > 1e-7"
        )

    # 3. loop.is_circle
    def test_loop_is_circle(self):
        loop: AnalyticTrimLoop = self.result["loop"]
        assert loop is not None
        assert loop.is_circle is True

    # 4. ORACLE: loop radius ≤ 1e-7 from cylinder radius
    def test_loop_radius_oracle(self):
        loop: AnalyticTrimLoop = self.result["loop"]
        assert abs(loop.semi_axis_a - 1.0) <= 1e-7, (
            f"radius {loop.semi_axis_a:.10f} != 1.0 (delta={abs(loop.semi_axis_a - 1.0):.3e})"
        )

    # 5. ORACLE: loop centre ≤ 1e-7 from (0,0,1)
    def test_loop_centre_oracle(self):
        loop: AnalyticTrimLoop = self.result["loop"]
        expected = np.array([0.0, 0.0, 1.0])
        dist = float(np.linalg.norm(loop.circle_center - expected))
        assert dist <= 1e-7, (
            f"centre {loop.circle_center} not within 1e-7 of {expected} "
            f"(dist={dist:.3e})"
        )

    # 6. face is not None
    def test_face_not_none(self):
        assert self.result["face"] is not None

    # 7. face.surface is the plane
    def test_face_surface_is_plane(self):
        from kerf_cad_core.geom.brep import Face
        face = self.result["face"]
        assert isinstance(face, Face)
        assert face.surface is self.plane

    # 8. face has exactly 1 loop for keep_side='inside' (disk)
    def test_face_has_one_loop_inside(self):
        face = self.result["face"]
        assert len(face.loops) == 1

    # 9. outer loop has 1 coedge (seam arc)
    def test_outer_loop_one_coedge(self):
        face = self.result["face"]
        outer = face.outer_loop()
        assert outer is not None
        assert len(outer.coedges) == 1

    # 10. seam vertex lies on the circle (≤ 1e-7)
    def test_seam_vertex_on_circle(self):
        from kerf_cad_core.geom.brep import CircleArc3
        face = self.result["face"]
        outer = face.outer_loop()
        ce = outer.coedges[0]
        v_seam = ce.start_vertex()
        loop: AnalyticTrimLoop = self.result["loop"]
        centre = loop.circle_center
        r = loop.semi_axis_a
        # seam vertex must be at distance r from circle centre in 3D
        dist = float(np.linalg.norm(v_seam.point - centre))
        assert abs(dist - r) <= 1e-7, (
            f"seam vertex dist from centre = {dist:.3e}, expected r={r:.3e}"
        )

    # 11. arc centre matches loop_centre
    def test_arc_centre_matches_loop(self):
        from kerf_cad_core.geom.brep import CircleArc3
        face = self.result["face"]
        outer = face.outer_loop()
        ce = outer.coedges[0]
        arc = ce.edge.curve
        assert isinstance(arc, CircleArc3)
        loop: AnalyticTrimLoop = self.result["loop"]
        dist = float(np.linalg.norm(arc.center - loop.circle_center))
        assert dist <= 1e-7, (
            f"arc.center {arc.center} != loop_centre {loop.circle_center} "
            f"(dist={dist:.3e})"
        )

    # 12. arc radius matches cylinder radius
    def test_arc_radius_matches_cylinder(self):
        from kerf_cad_core.geom.brep import CircleArc3
        face = self.result["face"]
        outer = face.outer_loop()
        arc = outer.coedges[0].edge.curve
        assert isinstance(arc, CircleArc3)
        assert abs(arc.radius - 1.0) <= 1e-7

    # 13. uv_boundary has `samples` entries
    def test_uv_boundary_length(self):
        uv = self.result["uv_boundary"]
        assert len(uv) == 256

    # 14. uv_boundary points re-evaluate to circle 3-D pts (≤ 1e-7)
    def test_uv_boundary_round_trip(self):
        uv = self.result["uv_boundary"]
        loop: AnalyticTrimLoop = self.result["loop"]
        centre = loop.circle_center
        r = loop.semi_axis_a
        for u, v_p in uv:
            pt = np.asarray(self.plane.evaluate(u, v_p), dtype=float)
            # pt must be at distance r from centre and at z=1
            dist_z = abs(pt[2] - 1.0)
            dist_r = abs(float(np.linalg.norm(pt[:2] - centre[:2])) - r)
            assert dist_z <= 1e-7, f"z={pt[2]:.3e} not at z=1"
            assert dist_r <= 1e-7, f"r={float(np.linalg.norm(pt[:2] - centre[:2])):.3e} != {r}"


# ---------------------------------------------------------------------------
# 15. keep_side='outside' → face with 2 loops (outer boundary + hole)
# ---------------------------------------------------------------------------

class TestSsiTrimOutsideSide:
    def setup_method(self):
        self.plane = _z_plane(z=0.0)
        self.cyl = _z_cylinder(r=1.0)
        self.result = trim_face_by_ssi(
            self.plane, self.cyl, keep_side="outside", samples=64, tol=1e-7
        )

    def test_ok(self):
        assert self.result["ok"] is True, self.result["reason"]

    def test_face_has_two_loops(self):
        face = self.result["face"]
        # outer boundary + 1 inner (hole) loop
        assert len(face.loops) == 2

    def test_outer_loop_is_outer(self):
        face = self.result["face"]
        outer = face.outer_loop()
        assert outer is not None
        assert outer.is_outer is True

    def test_inner_loop_is_inner(self):
        face = self.result["face"]
        inner_loops = face.inner_loops()
        assert len(inner_loops) == 1
        assert inner_loops[0].is_outer is False


# ---------------------------------------------------------------------------
# 16–18. Unsupported pairs + no-raise guarantee
# ---------------------------------------------------------------------------

class TestSsiTrimUnsupported:
    def setup_method(self):
        self.plane = _z_plane()
        self.sph = SphereSurface(center=np.array([0.0, 0.0, 0.0]), radius=1.0)
        self.cyl = _z_cylinder(r=1.0)

    # 16. unsupported pair → ok=False + reason has "unsupported-input"
    def test_plane_sphere_unsupported(self):
        res = trim_face_by_ssi(self.plane, self.sph)
        assert res["ok"] is False
        assert "unsupported-input" in res["reason"]

    # 17. unsupported pair → face is None
    def test_unsupported_face_is_none(self):
        res = trim_face_by_ssi(self.plane, self.sph)
        assert res["face"] is None

    # 18. never raises for any pair
    def test_no_raise_supported(self):
        try:
            r = trim_face_by_ssi(self.plane, self.cyl)
            assert isinstance(r, dict)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"raised for (Plane, Cylinder): {exc}")

    def test_no_raise_unsupported(self):
        try:
            r = trim_face_by_ssi(self.plane, self.sph)
            assert isinstance(r, dict)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"raised for (Plane, Sphere): {exc}")

    def test_no_raise_bad_keep_side(self):
        try:
            r = trim_face_by_ssi(self.plane, self.cyl, keep_side="banana")
            assert isinstance(r, dict)
            assert r["ok"] is False
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"raised for bad keep_side: {exc}")


# ---------------------------------------------------------------------------
# 19–20. Parametric oracle: varying radii + non-origin cylinder
# ---------------------------------------------------------------------------

class TestSsiTrimOracle:
    """High-precision oracle: the trim loop must match the exact geometry."""

    @pytest.mark.parametrize("r,h", [
        (0.5, 0.0),
        (1.0, 1.0),
        (2.5, -0.5),
        (0.1, 3.0),
    ])
    def test_varying_radius_and_height(self, r, h):
        """Loop radius and centre correct to 1e-7 for various r and h."""
        plane = _z_plane(z=h)
        cyl = _z_cylinder(r=r)
        res = trim_face_by_ssi(plane, cyl, keep_side="inside", samples=128)
        assert res["ok"] is True, res["reason"]
        assert res["residual_max"] <= 1e-7, (
            f"r={r}, h={h}: residual={res['residual_max']:.3e}"
        )
        loop: AnalyticTrimLoop = res["loop"]
        # ORACLE: radius
        assert abs(loop.semi_axis_a - r) <= 1e-7, (
            f"r={r}: got semi_a={loop.semi_axis_a:.10f}"
        )
        # ORACLE: centre z
        assert abs(loop.circle_center[2] - h) <= 1e-7, (
            f"h={h}: got centre_z={loop.circle_center[2]:.10f}"
        )

    @pytest.mark.parametrize("cx,cy,cz", [
        (0.0, 0.0, 0.0),
        (3.0, -2.0, 0.0),
        (-1.0, 4.0, -5.0),
    ])
    def test_non_origin_cylinder(self, cx, cy, cz):
        """Loop centre XY matches the cylinder axis position to 1e-7."""
        plane = _z_plane(z=cz + 1.0)
        cyl = _z_cylinder(cx=cx, cy=cy, cz=cz, r=1.0)
        res = trim_face_by_ssi(plane, cyl, keep_side="inside")
        assert res["ok"] is True, res["reason"]
        loop: AnalyticTrimLoop = res["loop"]
        expected = np.array([cx, cy, cz + 1.0])
        dist = float(np.linalg.norm(loop.circle_center - expected))
        assert dist <= 1e-7, (
            f"centre {loop.circle_center} != {expected} (dist={dist:.3e})"
        )


# ---------------------------------------------------------------------------
# 21. SsiTrimResult dataclass
# ---------------------------------------------------------------------------

class TestSsiTrimResultDataclass:
    def test_fields_accessible(self):
        r = SsiTrimResult(
            ok=True,
            reason="",
            face=None,
            loop=None,
            uv_boundary=[(0.0, 0.0)],
            residual_max=1e-10,
        )
        assert r.ok is True
        assert r.reason == ""
        assert r.face is None
        assert r.loop is None
        assert r.uv_boundary == [(0.0, 0.0)]
        assert r.residual_max == 1e-10


# ---------------------------------------------------------------------------
# 22. Importability from geom.__init__
# ---------------------------------------------------------------------------

class TestSsiTrimImport:
    def test_importable_from_geom_init(self):
        from kerf_cad_core.geom import (  # noqa: PLC0415
            AnalyticTrimLoop,
            SsiTrimResult,
            trim_face_analytic,
            trim_face_by_ssi,
        )
        assert callable(trim_face_by_ssi)
        assert callable(trim_face_analytic)
        assert SsiTrimResult is not None
        assert AnalyticTrimLoop is not None
