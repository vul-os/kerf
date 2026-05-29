"""Phase 4a Jewelry Priority Surfacing — opSweep2 / opNetworkSrf / opBlendSrf.

Tests that each of the three rebuilt Phase 4a surfacing operations produces
a ``validate_body``-clean open Shell Body from simple canonical inputs.

Canonical inputs
----------------
sweep2 : two parallel line rails + a short cross-section profile
networkSrf : a 2×2 grid of orthogonal line curves (``u_curves`` + ``v_curves``)
blendSrf   : two flat NurbsSurface planes adjacent at their seam edges

Success criteria (DoD)
----------------------
  * ``validate_body(body, open=True)["ok"] is True`` for each op.
  * The body has exactly one Face (one open Shell).
  * No numpy NaN / Inf in the surface control points.
  * LLM tool ToolSpec is importable and has correct ``name`` field.

Pure-Python, no database, no OCCT.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.geom.brep import validate_body
from kerf_cad_core.geom.brep_build import (
    sweep2_to_body,
    network_srf_to_body,
    blend_srf_to_body,
    BuildError,
)


# ---------------------------------------------------------------------------
# Shared curve / surface helpers
# ---------------------------------------------------------------------------

def _line_curve(p0, p1) -> NurbsCurve:
    """Degree-1 NURBS line segment, domain [0, 1]."""
    cp = np.array([p0, p1], dtype=float)
    return NurbsCurve(degree=1, control_points=cp, knots=np.array([0.0, 0.0, 1.0, 1.0]))


def _poly_curve(pts: np.ndarray, degree: int = 1) -> NurbsCurve:
    """Degree-*degree* NURBS open curve through *pts*, domain [0, 1]."""
    n = len(pts)
    d = min(degree, n - 1)
    knots = np.concatenate([
        np.zeros(d),
        np.linspace(0.0, 1.0, n - d + 1),
        np.ones(d),
    ])
    return NurbsCurve(degree=d, control_points=np.array(pts, dtype=float), knots=knots)


def _flat_surface(
    x0: float = 0.0, x1: float = 1.0,
    y0: float = 0.0, y1: float = 1.0,
    z: float = 0.0,
    n: int = 4,
) -> NurbsSurface:
    """Degree-1×1 flat NURBS plane patch with n×n control points."""
    xs = np.linspace(x0, x1, n)
    ys = np.linspace(y0, y1, n)
    cps = np.zeros((n, n, 3))
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            cps[i, j] = [x, y, z]
    degree = 1
    knots = np.concatenate([np.zeros(degree), np.linspace(0.0, 1.0, n - degree + 1), np.ones(degree)])
    return NurbsSurface(
        control_points=cps,
        degree_u=degree,
        degree_v=degree,
        knots_u=knots,
        knots_v=knots,
    )


# ---------------------------------------------------------------------------
# 1. opSweep2 — two-rail sweep
# ---------------------------------------------------------------------------

class TestOpSweep2:
    """Two-rail sweep (opSweep2 / sweep2_to_body) on simple canonical inputs.

    Canonical: cross-section segment (-0.5, 0, 0)->(0.5, 0, 0) swept between
    two parallel rails along Y-axis at x=0 and x=1 respectively.
    """

    def _make_inputs(self):
        profile = _line_curve([-0.5, 0.0, 0.0], [0.5, 0.0, 0.0])
        rail1   = _line_curve([0.0,  0.0, 0.0], [0.0,  2.0, 0.0])
        rail2   = _line_curve([1.0,  0.0, 0.0], [1.0,  2.0, 0.0])
        return profile, rail1, rail2

    def test_validate_body_clean(self):
        """sweep2_to_body produces a validate_body-clean open Body."""
        profile, rail1, rail2 = self._make_inputs()
        body = sweep2_to_body(profile, rail1, rail2)
        res = validate_body(body, open=True)
        assert res["ok"] is True, f"validate_body errors: {res['errors']}"

    def test_single_face(self):
        """Body must have exactly one Face (one open Shell)."""
        profile, rail1, rail2 = self._make_inputs()
        body = sweep2_to_body(profile, rail1, rail2)
        assert len(body.all_faces()) == 1

    def test_shell_open(self):
        """Produced Shell must be open (is_closed=False)."""
        profile, rail1, rail2 = self._make_inputs()
        body = sweep2_to_body(profile, rail1, rail2)
        shells = body.all_shells()
        assert len(shells) == 1
        assert shells[0].is_closed is False

    def test_no_nan_in_control_points(self):
        """Surface control points must not contain NaN or Inf."""
        profile, rail1, rail2 = self._make_inputs()
        body = sweep2_to_body(profile, rail1, rail2)
        face = body.all_faces()[0]
        surf = face.surface
        assert np.all(np.isfinite(surf.control_points)), "NaN/Inf in sweep2 control points"

    def test_surface_type_is_nurbs(self):
        """Face surface must be a NurbsSurface."""
        profile, rail1, rail2 = self._make_inputs()
        body = sweep2_to_body(profile, rail1, rail2)
        face = body.all_faces()[0]
        assert isinstance(face.surface, NurbsSurface)

    def test_sweep2_three_segment_rails(self):
        """Two-rail sweep with 4-point piecewise rails also produces valid body."""
        profile = _line_curve([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        pts1 = [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 2.0, 0.1], [0.0, 3.0, 0.0]]
        pts2 = [[1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [1.0, 2.0, 0.1], [1.0, 3.0, 0.0]]
        rail1 = _poly_curve(pts1, degree=1)
        rail2 = _poly_curve(pts2, degree=1)
        body = sweep2_to_body(profile, rail1, rail2)
        res = validate_body(body, open=True)
        assert res["ok"] is True, f"3-segment rails: validate_body errors: {res['errors']}"

    def test_llm_tool_spec_importable(self):
        """feature_sweep2 ToolSpec is importable from surfacing module."""
        from kerf_cad_core.surfacing import feature_sweep2_spec
        assert feature_sweep2_spec.name == "feature_sweep2"

    def test_llm_tool_run_function_exists(self):
        """run_feature_sweep2 async function is importable."""
        from kerf_cad_core.surfacing import run_feature_sweep2
        import inspect
        assert inspect.iscoroutinefunction(run_feature_sweep2)


# ---------------------------------------------------------------------------
# 2. opNetworkSrf — network surface
# ---------------------------------------------------------------------------

class TestOpNetworkSrf:
    """Network surface (opNetworkSrf / network_srf_to_body) on a 2×2 orthogonal
    grid of line curves.

    Canonical:
      u_curves (iso-v): two horizontal lines at v=0 and v=1
      v_curves (iso-u): two vertical lines at u=0 and u=1
      All four curves share the four corner points.
    """

    def _make_grid_curves(self):
        # u_curves: lines at y=0 and y=1, running from x=0..1 at z=0
        u0 = _line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        u1 = _line_curve([0.0, 1.0, 0.0], [1.0, 1.0, 0.0])
        # v_curves: lines at x=0 and x=1, running from y=0..1 at z=0
        v0 = _line_curve([0.0, 0.0, 0.0], [0.0, 1.0, 0.0])
        v1 = _line_curve([1.0, 0.0, 0.0], [1.0, 1.0, 0.0])
        return [u0, u1], [v0, v1]

    def test_validate_body_clean(self):
        """network_srf_to_body produces a validate_body-clean open Body."""
        u_curves, v_curves = self._make_grid_curves()
        body = network_srf_to_body(u_curves, v_curves)
        res = validate_body(body, open=True)
        assert res["ok"] is True, f"validate_body errors: {res['errors']}"

    def test_single_face(self):
        """Body must have exactly one Face."""
        u_curves, v_curves = self._make_grid_curves()
        body = network_srf_to_body(u_curves, v_curves)
        assert len(body.all_faces()) == 1

    def test_shell_open(self):
        """Produced Shell must be open."""
        u_curves, v_curves = self._make_grid_curves()
        body = network_srf_to_body(u_curves, v_curves)
        shells = body.all_shells()
        assert len(shells) == 1
        assert shells[0].is_closed is False

    def test_no_nan_in_control_points(self):
        """Network surface control points must not contain NaN or Inf."""
        u_curves, v_curves = self._make_grid_curves()
        body = network_srf_to_body(u_curves, v_curves)
        face = body.all_faces()[0]
        surf = face.surface
        assert np.all(np.isfinite(surf.control_points)), "NaN/Inf in network_srf control points"

    def test_surface_type_is_nurbs(self):
        """Face surface must be a NurbsSurface."""
        u_curves, v_curves = self._make_grid_curves()
        body = network_srf_to_body(u_curves, v_curves)
        face = body.all_faces()[0]
        assert isinstance(face.surface, NurbsSurface)

    def test_four_curve_network(self):
        """Network from 2 u + 2 v curves (4-curve network) produces valid body."""
        # Identical to the main case — verifies the canonical 4-curve network
        u_curves, v_curves = self._make_grid_curves()
        body = network_srf_to_body(u_curves, v_curves)
        res = validate_body(body, open=True)
        assert res["ok"] is True, f"4-curve network errors: {res['errors']}"

    def test_too_few_u_curves_raises(self):
        """Fewer than 2 u_curves raises ValueError."""
        _, v_curves = self._make_grid_curves()
        u0 = _line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        with pytest.raises(ValueError, match="u_curves"):
            network_srf_to_body([u0], v_curves)

    def test_too_few_v_curves_raises(self):
        """Fewer than 2 v_curves raises ValueError."""
        u_curves, _ = self._make_grid_curves()
        v0 = _line_curve([0.0, 0.0, 0.0], [0.0, 1.0, 0.0])
        with pytest.raises(ValueError, match="v_curves"):
            network_srf_to_body(u_curves, [v0])

    def test_llm_tool_spec_importable(self):
        """feature_network_srf ToolSpec is importable from surfacing module."""
        from kerf_cad_core.surfacing import feature_network_srf_spec
        assert feature_network_srf_spec.name == "feature_network_srf"

    def test_llm_tool_run_function_exists(self):
        """run_feature_network_srf async function is importable."""
        from kerf_cad_core.surfacing import run_feature_network_srf
        import inspect
        assert inspect.iscoroutinefunction(run_feature_network_srf)


# ---------------------------------------------------------------------------
# 3. opBlendSrf — continuous blend surface
# ---------------------------------------------------------------------------

class TestOpBlendSrf:
    """Blend surface (opBlendSrf / blend_srf_to_body) between two adjacent
    flat NurbsSurface planes.

    Canonical:
      surf1: flat plane at y in [0, 1], x in [0, 1], z=0
      surf2: flat plane at y in [2, 3], x in [0, 1], z=0
      Both share the same x-range; blend in the v direction.
    """

    def _make_adjacent_planes(self):
        """Two flat planes adjacent in the v direction (y=1 / y=2 gap)."""
        surf1 = _flat_surface(x0=0.0, x1=1.0, y0=0.0, y1=1.0, z=0.0, n=4)
        surf2 = _flat_surface(x0=0.0, x1=1.0, y0=2.0, y1=3.0, z=0.0, n=4)
        return surf1, surf2

    def test_validate_body_clean_g1(self):
        """blend_srf_to_body (G1) produces a validate_body-clean open Body."""
        surf1, surf2 = self._make_adjacent_planes()
        body = blend_srf_to_body(surf1, surf2, continuity="G1")
        res = validate_body(body, open=True)
        assert res["ok"] is True, f"G1 blend validate_body errors: {res['errors']}"

    def test_validate_body_clean_g2(self):
        """blend_srf_to_body (G2) produces a validate_body-clean open Body."""
        surf1, surf2 = self._make_adjacent_planes()
        body = blend_srf_to_body(surf1, surf2, continuity="G2")
        res = validate_body(body, open=True)
        assert res["ok"] is True, f"G2 blend validate_body errors: {res['errors']}"

    def test_single_face(self):
        """Body must have exactly one Face."""
        surf1, surf2 = self._make_adjacent_planes()
        body = blend_srf_to_body(surf1, surf2)
        assert len(body.all_faces()) == 1

    def test_shell_open(self):
        """Produced Shell must be open."""
        surf1, surf2 = self._make_adjacent_planes()
        body = blend_srf_to_body(surf1, surf2)
        shells = body.all_shells()
        assert len(shells) == 1
        assert shells[0].is_closed is False

    def test_no_nan_in_control_points_g1(self):
        """G1 blend control points must not contain NaN or Inf."""
        surf1, surf2 = self._make_adjacent_planes()
        body = blend_srf_to_body(surf1, surf2, continuity="G1")
        face = body.all_faces()[0]
        surf = face.surface
        assert np.all(np.isfinite(surf.control_points)), "NaN/Inf in G1 blend control points"

    def test_no_nan_in_control_points_g2(self):
        """G2 blend control points must not contain NaN or Inf."""
        surf1, surf2 = self._make_adjacent_planes()
        body = blend_srf_to_body(surf1, surf2, continuity="G2")
        face = body.all_faces()[0]
        surf = face.surface
        assert np.all(np.isfinite(surf.control_points)), "NaN/Inf in G2 blend control points"

    def test_g1_strip_has_4_rows(self):
        """G1 blend strip (degree-3 Bezier) must have 4 control rows in v."""
        surf1, surf2 = self._make_adjacent_planes()
        body = blend_srf_to_body(surf1, surf2, continuity="G1")
        face = body.all_faces()[0]
        surf = face.surface
        assert surf.num_control_points_v == 4, (
            f"G1 blend expected 4 cv rows in v, got {surf.num_control_points_v}"
        )

    def test_g2_strip_has_6_rows(self):
        """G2 blend strip (degree-5 Bezier) must have 6 control rows in v."""
        surf1, surf2 = self._make_adjacent_planes()
        body = blend_srf_to_body(surf1, surf2, continuity="G2")
        face = body.all_faces()[0]
        surf = face.surface
        assert surf.num_control_points_v == 6, (
            f"G2 blend expected 6 cv rows in v, got {surf.num_control_points_v}"
        )

    def test_blend_default_continuity_is_g1(self):
        """Default continuity is G1 (degree-3 Bezier, 4 cv rows in v)."""
        surf1, surf2 = self._make_adjacent_planes()
        body = blend_srf_to_body(surf1, surf2)
        face = body.all_faces()[0]
        assert face.surface.num_control_points_v == 4

    def test_llm_tool_spec_importable(self):
        """feature_blend_srf ToolSpec is importable from surfacing module."""
        from kerf_cad_core.surfacing import feature_blend_srf_spec
        assert feature_blend_srf_spec.name == "feature_blend_srf"

    def test_llm_tool_run_function_exists(self):
        """run_feature_blend_srf async function is importable."""
        from kerf_cad_core.surfacing import run_feature_blend_srf
        import inspect
        assert inspect.iscoroutinefunction(run_feature_blend_srf)


# ---------------------------------------------------------------------------
# 4. Cross-op: all three ops are importable from brep_build __all__
# ---------------------------------------------------------------------------

class TestPhase4aExports:
    """All three Phase 4a builder functions are in brep_build.__all__."""

    def test_network_srf_to_body_in_all(self):
        from kerf_cad_core.geom import brep_build
        assert "network_srf_to_body" in brep_build.__all__

    def test_blend_srf_to_body_in_all(self):
        from kerf_cad_core.geom import brep_build
        assert "blend_srf_to_body" in brep_build.__all__

    def test_sweep2_to_body_in_all(self):
        from kerf_cad_core.geom import brep_build
        assert "sweep2_to_body" in brep_build.__all__

    def test_all_three_llm_tools_registered(self):
        """All three LLM ToolSpecs have distinct, correct tool names."""
        from kerf_cad_core.surfacing import (
            feature_sweep2_spec,
            feature_network_srf_spec,
            feature_blend_srf_spec,
        )
        names = {feature_sweep2_spec.name, feature_network_srf_spec.name, feature_blend_srf_spec.name}
        assert names == {"feature_sweep2", "feature_network_srf", "feature_blend_srf"}
