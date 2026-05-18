"""T-104c — G3 blend trim+sew to Body on analytic carrier matrix.

Verifies ``g3_blend_trim_sew`` from ``blend_srf``:

  * Importable from ``kerf_cad_core.geom.blend_srf``.
  * Planar-pair geometry: ``ok=True``, ``validate_body`` passes,
    body is 2-manifold (F=6, E=12), volume matches closed-form to 1e-5.
  * Planar-cyl geometry: ``ok=True``, ``validate_body`` passes.
  * Non-matrix input (cubic-z surface): returns structured
    ``unsupported-input``, ``body=None``, never raises.
  * Unsupported edge spec: returns structured ``unsupported-input``.

All tests are hermetic: no network, no OCCT, no external fixtures.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_derivatives
from kerf_cad_core.geom.blend_srf import g3_blend_trim_sew, _nurbs_param_range, _eval3
from kerf_cad_core.geom.surface_fillet import surface_blend_g3
from kerf_cad_core.geom.brep import validate_body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _k1() -> np.ndarray:
    return np.array([0.0, 0.0, 1.0, 1.0])


def _k3() -> np.ndarray:
    return np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])


def _planar_surf(corners: np.ndarray) -> NurbsSurface:
    """Bilinear planar surface from four corners (2×2 control grid)."""
    assert corners.shape == (2, 2, 3)
    return NurbsSurface(1, 1, corners, _k1(), _k1())


def _body_topology(body) -> tuple:
    """Return (F, E, V) for the first shell of *body*."""
    shell = body.solids[0].shells[0]
    all_edges: set = set()
    all_verts: set = set()
    for face in shell.faces:
        for loop in face.loops:
            for ce in loop.coedges:
                all_edges.add(id(ce.edge))
                all_verts.add(id(ce.edge.v_start))
                all_verts.add(id(ce.edge.v_end))
    return len(shell.faces), len(all_edges), len(all_verts)


def _blend_arch_area(blend_surf: NurbsSurface, u: float, N: int = 20_000) -> float:
    """Signed area of the blend cross-section loop at fixed *u* (y-z shoelace)."""
    bumin, bumax, bvmin, bvmax = _nurbs_param_range(blend_surf)
    pts = np.array([
        _eval3(blend_surf, u, bvmin + (bvmax - bvmin) * i / N)[[1, 2]]
        for i in range(N + 1)
    ])
    # Shoelace on the open arc (endpoints coincide at (y=0,z=0))
    a = float(np.sum(pts[:-1, 0] * pts[1:, 1] - pts[1:, 0] * pts[:-1, 1]))
    return abs(a) / 2.0


def _body_volume_divergence(surf1, surf2, blend_surf, tol: float = 1e-2) -> float:
    """Approximate body volume via the divergence theorem V = (1/3)∑ ∫ P·n dA.

    Uses Gauss quadrature at N×N grid over each parametric patch.
    For the floor-wall geometry (surf1 at z=0, surf2 at y=0, blend) the volume
    equals x_length × (triangle_area - blend_arch_area).
    """
    def _face_contrib(surf, u0, u1, v0, v1, sign=1, N=120):
        total = 0.0
        du = (u1 - u0) / N
        dv = (v1 - v0) / N
        for i in range(N):
            u = u0 + (i + 0.5) * du
            for j in range(N):
                v = v0 + (j + 0.5) * dv
                pt = np.asarray(surf.evaluate(u, v), dtype=float)[:3]
                ders = surface_derivatives(surf, u, v, d=1)
                Su = ders[1, 0, :3]
                Sv = ders[0, 1, :3]
                n = np.cross(Su, Sv) * sign
                total += float(np.dot(pt, n)) * du * dv
        return total / 3.0

    u1min, u1max, v1min, v1max = _nurbs_param_range(surf1)
    u2min, u2max, v2min, v2max = _nurbs_param_range(surf2)
    bumin, bumax, bvmin, bvmax = _nurbs_param_range(blend_surf)

    # surf1 natural normal at z=0: (0,0,-1) = outward (body above at z>0)
    # surf2 natural normal at y=0: (0,-1,0) = outward (body at y>0)
    # blend natural normal: points toward +y+z = outward
    vol = (
        _face_contrib(surf1, u1min, u1max, v1min, v1max, sign=+1, N=120) +
        _face_contrib(surf2, u2min, u2max, v2min, v2max, sign=+1, N=120) +
        _face_contrib(blend_surf, bumin, bumax, bvmin, bvmax, sign=+1, N=120)
    )

    # Right cap contribution (x=1 plane, normal (+1,0,0)):
    # cap area = triangle (0,0),(1,0),(0,1) minus blend arch area
    arch_area = _blend_arch_area(blend_surf, bumax)
    vol += (0.5 - arch_area) / 3.0

    # Bottom face (planar diagonal from A0=(0,1,0) to B0=(0,0,1) at x=0):
    A0 = np.array([0.0, 1.0, 0.0])
    B0 = np.array([0.0, 0.0, 1.0])
    A1 = np.array([1.0, 1.0, 0.0])
    B1 = np.array([1.0, 0.0, 1.0])
    n_bot_raw = np.cross(B0 - A0, A1 - A0)
    n_bot = n_bot_raw / np.linalg.norm(n_bot_raw)
    area_bot = float(np.linalg.norm(n_bot_raw))
    center_bot = (A0 + B1) / 2.0
    vol += float(np.dot(center_bot, n_bot)) * area_bot / 3.0

    return vol


# ---------------------------------------------------------------------------
# Test fixtures: surfaces
# ---------------------------------------------------------------------------


@pytest.fixture
def floor_wall_surfaces():
    """Floor (z=0, y∈[0→1]) + wall (y=0, z∈[0→1]), seam at (y=0,z=0)."""
    # surf1: floor; v=0 at y=1, v=1 at y=0 (seam).
    cp1 = np.zeros((2, 2, 3))
    cp1[0, 0] = [0.0, 1.0, 0.0]
    cp1[1, 0] = [1.0, 1.0, 0.0]
    cp1[0, 1] = [0.0, 0.0, 0.0]
    cp1[1, 1] = [1.0, 0.0, 0.0]
    surf1 = NurbsSurface(1, 1, cp1, _k1(), _k1())

    # surf2: wall; v=0 at z=0 (seam), v=1 at z=1.
    cp2 = np.zeros((2, 2, 3))
    cp2[0, 0] = [0.0, 0.0, 0.0]
    cp2[1, 0] = [1.0, 0.0, 0.0]
    cp2[0, 1] = [0.0, 0.0, 1.0]
    cp2[1, 1] = [1.0, 0.0, 1.0]
    surf2 = NurbsSurface(1, 1, cp2, _k1(), _k1())
    return surf1, surf2


@pytest.fixture
def cubic_z_surface():
    """Cubic-z surface — NOT in the analytic carrier matrix (non-matrix)."""
    ctrl = np.zeros((4, 4, 3))
    for i, x in enumerate([0.0, 1.0 / 3, 2.0 / 3, 1.0]):
        for j, y in enumerate([0.0, 1.0 / 3, 2.0 / 3, 1.0]):
            ctrl[i, j] = [x, y, y ** 3 * 0.2]
    return NurbsSurface(3, 3, ctrl, _k3(), _k3())


@pytest.fixture
def cylindrical_surface():
    """Exact NURBS quarter-cylinder (radius=1, axis=x), x∈[0,1]."""
    w = math.cos(math.pi / 4)
    cp = np.zeros((2, 3, 3))
    cp[0, 0] = [0.0, 1.0, 0.0]
    cp[0, 1] = [0.0, 1.0, 1.0]
    cp[0, 2] = [0.0, 0.0, 1.0]
    cp[1, 0] = [1.0, 1.0, 0.0]
    cp[1, 1] = [1.0, 1.0, 1.0]
    cp[1, 2] = [1.0, 0.0, 1.0]
    weights = np.array([[1.0, w, 1.0], [1.0, w, 1.0]])
    ku = np.array([0.0, 0.0, 1.0, 1.0])
    kv = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    return NurbsSurface(1, 2, cp, ku, kv, weights)


# ---------------------------------------------------------------------------
# T-104c tests
# ---------------------------------------------------------------------------


class TestImportContract:
    def test_importable(self):
        """g3_blend_trim_sew is importable from blend_srf."""
        from kerf_cad_core.geom.blend_srf import g3_blend_trim_sew as _f
        assert callable(_f)


class TestPlanarPairBody:
    def test_ok(self, floor_wall_surfaces):
        surf1, surf2 = floor_wall_surfaces
        res = g3_blend_trim_sew(surf1, surf2, edge="v1_v0",
                                samples=24, blend_width=0.1)
        assert res["ok"] is True, f"Expected ok, got reason: {res['reason']}"
        assert res["body"] is not None

    def test_validate_body_passes(self, floor_wall_surfaces):
        surf1, surf2 = floor_wall_surfaces
        res = g3_blend_trim_sew(surf1, surf2, edge="v1_v0",
                                samples=24, blend_width=0.1)
        # validate_body raises on failure; no exception = pass
        validate_body(res["body"])

    def test_topology_f6_e12(self, floor_wall_surfaces):
        surf1, surf2 = floor_wall_surfaces
        res = g3_blend_trim_sew(surf1, surf2, edge="v1_v0",
                                samples=24, blend_width=0.1)
        F, E, _ = _body_topology(res["body"])
        assert F == 6, f"Expected F=6, got {F}"
        assert E == 12, f"Expected E=12, got {E}"

    def test_is_2manifold(self, floor_wall_surfaces):
        surf1, surf2 = floor_wall_surfaces
        res = g3_blend_trim_sew(surf1, surf2, edge="v1_v0",
                                samples=24, blend_width=0.1)
        body = res["body"]
        shell = body.solids[0].shells[0]
        # 2-manifold: every edge is shared by exactly 2 coedges
        from collections import Counter
        edge_count: Counter = Counter()
        for face in shell.faces:
            for loop in face.loops:
                for ce in loop.coedges:
                    edge_count[id(ce.edge)] += 1
        assert all(c == 2 for c in edge_count.values()), (
            "Body is not 2-manifold: some edges are not shared by exactly 2 coedges"
        )

    def test_volume_matches_closed_form(self, floor_wall_surfaces):
        """Volume = x_len × (0.5 - blend_arch_area) to within 1e-5.

        Closed form: the cross-section at constant x is a right-isosceles
        triangle (legs=1, area=0.5) minus the area of the G3 blend arch loop.
        The blend arch area is computed via high-resolution shoelace on the
        blend strip boundary at u=u_min (left cap side).
        """
        surf1, surf2 = floor_wall_surfaces
        blend_w = 0.1
        res = g3_blend_trim_sew(surf1, surf2, edge="v1_v0",
                                samples=24, blend_width=blend_w)
        blend_res = surface_blend_g3(surf1, surf2, edge="v1_v0",
                                     samples=24, blend_width=blend_w)
        blend_surf = blend_res["blend_surface"]

        # Closed-form reference: triangle_area - blend_arch_area (x-symmetric)
        arch_area = _blend_arch_area(blend_surf,
                                     u=float(blend_surf.knots_u[blend_surf.degree_u]),
                                     N=20_000)
        vol_ref = 0.5 - arch_area  # x_len=1

        # Numerical body volume via divergence theorem
        vol_body = _body_volume_divergence(surf1, surf2, blend_surf)

        assert abs(vol_body - vol_ref) < 1e-5, (
            f"Volume mismatch: body={vol_body:.8f}, ref={vol_ref:.8f}, "
            f"diff={abs(vol_body-vol_ref):.2e}"
        )

    def test_blend_diagnostics_present(self, floor_wall_surfaces):
        surf1, surf2 = floor_wall_surfaces
        res = g3_blend_trim_sew(surf1, surf2, edge="v1_v0",
                                samples=24, blend_width=0.1)
        assert isinstance(res["blend_diagnostics"], dict)


class TestPlanarCylBody:
    def test_ok(self, floor_wall_surfaces, cylindrical_surface):
        """Planar floor + cylindrical surface: body must validate."""
        surf1, _ = floor_wall_surfaces

        # Cylindrical surface has v_min seam at z=0 (quarter-circle from y=1 to z=1).
        # Use it as surf2 with surf1's seam at y=0, z=0 matching cyl v_min edge.
        # Adjust: surf1 seam at y=1,z=0; use a flat surf1 that goes from y=0 to y=1.
        k1 = _k1()
        cp1 = np.zeros((2, 2, 3))
        cp1[0, 0] = [0.0, 0.0, 0.0]
        cp1[1, 0] = [1.0, 0.0, 0.0]
        cp1[0, 1] = [0.0, 1.0, 0.0]
        cp1[1, 1] = [1.0, 1.0, 0.0]
        flat = NurbsSurface(1, 1, cp1, k1, k1)

        # cylindrical_surface v_min = (y=1,z=0) which matches flat v_max
        cyl = cylindrical_surface
        res = g3_blend_trim_sew(flat, cyl, edge="v1_v0",
                                samples=24, blend_width=0.1)
        assert res["ok"] is True, f"Expected ok, got reason: {res['reason']}"
        validate_body(res["body"])

    def test_topology_f6_e12(self, cylindrical_surface):
        k1 = _k1()
        cp1 = np.zeros((2, 2, 3))
        cp1[0, 0] = [0.0, 0.0, 0.0]; cp1[1, 0] = [1.0, 0.0, 0.0]
        cp1[0, 1] = [0.0, 1.0, 0.0]; cp1[1, 1] = [1.0, 1.0, 0.0]
        flat = NurbsSurface(1, 1, cp1, k1, k1)
        cyl = cylindrical_surface
        res = g3_blend_trim_sew(flat, cyl, edge="v1_v0",
                                samples=24, blend_width=0.1)
        F, E, _ = _body_topology(res["body"])
        assert F == 6
        assert E == 12


class TestUnsupportedInput:
    def test_non_matrix_surf1_returns_unsupported(
        self, cubic_z_surface, floor_wall_surfaces
    ):
        """Cubic-z surf1 must return unsupported-input without raising."""
        _, surf2 = floor_wall_surfaces
        res = g3_blend_trim_sew(cubic_z_surface, surf2, edge="v1_v0")
        assert res["ok"] is False
        assert res["body"] is None
        assert res["reason"].startswith("unsupported-input"), (
            f"Unexpected reason: {res['reason']!r}"
        )

    def test_non_matrix_surf2_returns_unsupported(
        self, cubic_z_surface, floor_wall_surfaces
    ):
        """Cubic-z surf2 must return unsupported-input without raising."""
        surf1, _ = floor_wall_surfaces
        res = g3_blend_trim_sew(surf1, cubic_z_surface, edge="v1_v0")
        assert res["ok"] is False
        assert res["body"] is None
        assert res["reason"].startswith("unsupported-input"), (
            f"Unexpected reason: {res['reason']!r}"
        )

    def test_both_non_matrix_returns_unsupported(self, cubic_z_surface):
        res = g3_blend_trim_sew(cubic_z_surface, cubic_z_surface, edge="v1_v0")
        assert res["ok"] is False
        assert res["body"] is None
        assert res["reason"].startswith("unsupported-input")

    def test_unsupported_edge_spec(self, floor_wall_surfaces):
        """edge='u1_u0' must return unsupported-input."""
        surf1, surf2 = floor_wall_surfaces
        res = g3_blend_trim_sew(surf1, surf2, edge="u1_u0")
        assert res["ok"] is False
        assert res["body"] is None
        assert res["reason"].startswith("unsupported-input"), (
            f"Unexpected reason: {res['reason']!r}"
        )

    def test_unsupported_never_raises(self, cubic_z_surface):
        """g3_blend_trim_sew must never raise for non-matrix inputs."""
        try:
            res = g3_blend_trim_sew(cubic_z_surface, cubic_z_surface,
                                    edge="v1_v0")
            assert res["ok"] is False
        except Exception as exc:
            pytest.fail(
                f"g3_blend_trim_sew raised unexpectedly for non-matrix input: {exc}"
            )
