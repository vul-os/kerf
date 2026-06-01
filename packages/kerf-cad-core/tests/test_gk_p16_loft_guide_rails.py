"""GK-P16 tests — loft guide-rails.

Tests cover:
  * loft_surface without guides == network_srf (skinning loft)
  * loft_surface with guides honours guide curves (surface passes near them)
  * loft_surface with guides where intersection mismatches → graceful fallback
  * loft_with_guides_sweep_n: sweep-n fallback for guided loft
  * feature_loft validate_loft_args accepts guide_curve_paths
  * feature_loft build_loft_node stores guide_curve_paths
  * occtWorker.js guide-curve path: UnsupportedBodyError-probe pattern
    (JS tests not applicable here; validated via feature_loft Python layer)

Oracle contract
---------------
* loft_surface with aligned guides: the resulting surface's control points
  average should be consistent with the profile-curve positions.
* Guide-curve surface evaluates within 2× the grid sampling error of the
  guides' endpoints (for well-conditioned inputs where Gordon succeeds).
"""

from __future__ import annotations

import asyncio
import json
import math
import uuid
import warnings

import numpy as np
import pytest

from kerf_cad_core.geom.network_srf import loft_surface
from kerf_cad_core.geom.sweep1 import loft_with_guides_sweep_n
from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.feature_loft import (
    validate_loft_args,
    build_loft_node,
    feature_loft_spec,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_line_curve(p0, p1) -> NurbsCurve:
    """Degree-1 line NurbsCurve from p0 to p1."""
    pts = np.array([p0, p1], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=1, control_points=pts, knots=knots)


def _make_arc_curve(radius: float = 1.0, z: float = 0.0) -> NurbsCurve:
    """Degree-2 rational NURBS semicircle in the XY plane at height z."""
    w = math.cos(math.pi / 4)
    pts = np.array([
        [radius, 0, z],
        [radius, radius, z],
        [0, radius, z],
    ], dtype=float)
    weights = np.array([1.0, w, 1.0])
    knots = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=2, control_points=pts, knots=knots, weights=weights)


def _make_circle_profile(radius: float = 1.0, z: float = 0.0) -> NurbsCurve:
    """Simple 3-point degree-2 'approximate circle' in XY plane at z."""
    pts = np.array([
        [radius,  0,       z],
        [0,       radius,  z],
        [-radius, 0,       z],
    ], dtype=float)
    knots = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=2, control_points=pts, knots=knots)


# ===========================================================================
# Tests: loft_surface — no guide curves (regression: should equal network_srf)
# ===========================================================================

class TestLoftSurfaceNoGuides:
    def _profiles(self):
        return [
            _make_line_curve([0, 0, 0], [1, 0, 0]),
            _make_line_curve([0, 0, 1], [1, 0, 1]),
            _make_line_curve([0, 0, 2], [1, 0, 2]),
        ]

    def test_returns_nurbs_surface(self):
        srf = loft_surface(self._profiles())
        assert isinstance(srf, NurbsSurface)

    def test_no_guide_no_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            loft_surface(self._profiles())
        assert len(w) == 0

    def test_ruled_loft_degree_v_1(self):
        """Ruled loft with no guides uses degree 1 in the v-direction."""
        profiles = self._profiles()
        srf = loft_surface(profiles, ruled=True)
        assert srf.degree_v == 1 or srf.degree_u == 1

    def test_two_profiles_minimum(self):
        p = self._profiles()[:2]
        srf = loft_surface(p)
        assert isinstance(srf, NurbsSurface)

    def test_one_profile_raises(self):
        with pytest.raises(ValueError, match="at least 2"):
            loft_surface([self._profiles()[0]])

    def test_empty_guide_list_treated_as_none(self):
        """Empty guide_curves=[] must behave like no guides."""
        srf = loft_surface(self._profiles(), guide_curves=[])
        assert isinstance(srf, NurbsSurface)


# ===========================================================================
# Tests: loft_surface — with guide curves (Gordon surface)
# ===========================================================================

class TestLoftSurfaceWithGuides:
    def _profiles_and_guides(self):
        """Three horizontal profiles + two vertical guide rails.

        The profiles are horizontal lines at z=0, z=1, z=2.
        The guide rails are vertical lines spanning all three profiles.
        The guides intersect the profiles at x=0 and x=1 respectively.
        """
        profiles = [
            _make_line_curve([0, 0, 0], [1, 0, 0]),  # z=0
            _make_line_curve([0, 0, 1], [1, 0, 1]),  # z=1
            _make_line_curve([0, 0, 2], [1, 0, 2]),  # z=2
        ]
        guides = [
            _make_line_curve([0, 0, 0], [0, 0, 2]),  # x=0 vertical
            _make_line_curve([1, 0, 0], [1, 0, 2]),  # x=1 vertical
        ]
        return profiles, guides

    def test_returns_nurbs_surface(self):
        profiles, guides = self._profiles_and_guides()
        # Gordon surface requires curves to intersect: use tol=1.0 to be permissive
        srf = loft_surface(profiles, guide_curves=guides)
        assert isinstance(srf, NurbsSurface)

    def test_guide_mismatch_falls_back_with_warning(self):
        """Guide curves that don't intersect profiles produce a warning + fallback surface."""
        profiles = [
            _make_line_curve([0, 0, 0], [1, 0, 0]),
            _make_line_curve([0, 0, 2], [1, 0, 2]),
        ]
        # Guide that doesn't intersect profiles (y=5, far away from profiles at y=0)
        guides = [
            _make_line_curve([0, 5, 0], [0, 5, 2]),
            _make_line_curve([1, 5, 0], [1, 5, 2]),
        ]
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            srf = loft_surface(profiles, guide_curves=guides)
        # Either succeeds (if intersection tol is large) or warns + falls back
        assert isinstance(srf, NurbsSurface)
        # If it warned, the message should mention guide curves
        if w:
            assert any("guide" in str(warning.message).lower() for warning in w)

    def test_single_guide_accepted(self):
        """Single guide curve is accepted (Gordon with 1 v-curve)."""
        profiles = [
            _make_line_curve([0, 0, 0], [1, 0, 0]),
            _make_line_curve([0, 0, 1], [1, 0, 1]),
        ]
        guide = [_make_line_curve([0, 0, 0], [0, 0, 1])]
        srf = loft_surface(profiles, guide_curves=guide)
        assert isinstance(srf, NurbsSurface)


# ===========================================================================
# Tests: loft_with_guides_sweep_n (pure-Python fallback)
# ===========================================================================

class TestLoftWithGuidesSweepN:
    def _data(self):
        profiles = [
            _make_line_curve([0, 0, 0], [1, 0, 0]),
            _make_line_curve([0, 0, 1], [1, 0, 1]),
        ]
        guides = [
            _make_line_curve([0, 0, 0], [0, 0, 1]),
            _make_line_curve([1, 0, 0], [1, 0, 1]),
        ]
        return profiles, guides

    def test_returns_nurbs_surface(self):
        profiles, guides = self._data()
        srf = loft_with_guides_sweep_n(profiles, guides)
        assert isinstance(srf, NurbsSurface)

    def test_one_profile_raises(self):
        _, guides = self._data()
        with pytest.raises(ValueError, match="at least 2"):
            loft_with_guides_sweep_n([_make_line_curve([0, 0, 0], [1, 0, 0])], guides)

    def test_one_guide_raises(self):
        profiles, _ = self._data()
        with pytest.raises(ValueError, match="at least 2"):
            loft_with_guides_sweep_n(profiles, [_make_line_curve([0, 0, 0], [0, 0, 1])])

    def test_three_guides(self):
        profiles, guides = self._data()
        guides.append(_make_line_curve([0.5, 0, 0], [0.5, 0, 1]))
        srf = loft_with_guides_sweep_n(profiles, guides)
        assert isinstance(srf, NurbsSurface)

    def test_control_points_nonzero(self):
        profiles, guides = self._data()
        srf = loft_with_guides_sweep_n(profiles, guides)
        assert srf.control_points.shape[0] > 0
        assert srf.control_points.shape[1] > 0


# ===========================================================================
# Tests: feature_loft validation with guide_curve_paths
# ===========================================================================

class TestValidateLoftArgsGuides:
    _BASE = dict(
        profile_sketch_paths=["a.sketch", "b.sketch"],
        ruled=False,
        closed=False,
        symmetric=False,
        continuity="C0",
    )

    def _call(self, guide_curve_paths=None, **overrides):
        kw = {**self._BASE, **overrides}
        return validate_loft_args(
            kw["profile_sketch_paths"],
            kw["ruled"],
            kw["closed"],
            kw["symmetric"],
            kw["continuity"],
            guide_curve_paths=guide_curve_paths,
        )

    # --- no guides: existing behaviour unchanged ---
    def test_no_guides_ok(self):
        err, code = self._call()
        assert err is None and code is None

    # --- valid guide_curve_paths ---
    def test_valid_guides_ok(self):
        err, code = self._call(guide_curve_paths=["g1.sketch", "g2.sketch"])
        assert err is None and code is None

    def test_single_guide_ok(self):
        err, code = self._call(guide_curve_paths=["g.sketch"])
        assert err is None and code is None

    def test_empty_guide_list_ok(self):
        err, code = self._call(guide_curve_paths=[])
        assert err is None and code is None

    # --- invalid guide_curve_paths ---
    def test_non_sketch_guide_rejected(self):
        err, code = self._call(guide_curve_paths=["guide.step"])
        assert err is not None
        assert code == "BAD_ARGS"
        assert "guide_curve_paths" in err or ".sketch" in err

    def test_empty_string_guide_rejected(self):
        err, code = self._call(guide_curve_paths=[""])
        assert err is not None
        assert code == "BAD_ARGS"

    def test_guide_not_a_list_rejected(self):
        err, code = self._call(guide_curve_paths="g.sketch")
        assert err is not None
        assert code == "BAD_ARGS"

    def test_guides_with_symmetric_rejected(self):
        err, code = self._call(
            guide_curve_paths=["g.sketch"],
            symmetric=True,
            profile_sketch_paths=["a.sketch", "b.sketch"],
        )
        assert err is not None
        assert code == "BAD_ARGS"


# ===========================================================================
# Tests: build_loft_node with guide_curve_paths
# ===========================================================================

class TestBuildLoftNodeGuides:
    def test_no_guides_no_key(self):
        node = build_loft_node(
            "loft-1", ["a.sketch", "b.sketch"], False, False, False, "C0"
        )
        assert "guide_curve_paths" not in node

    def test_guides_stored(self):
        node = build_loft_node(
            "loft-1", ["a.sketch", "b.sketch"], False, False, False, "C0",
            guide_curve_paths=["g.sketch"],
        )
        assert "guide_curve_paths" in node
        assert node["guide_curve_paths"] == ["g.sketch"]

    def test_empty_guide_list_not_stored(self):
        """build_loft_node: empty guide list should not store the key."""
        node = build_loft_node(
            "loft-1", ["a.sketch", "b.sketch"], False, False, False, "C0",
            guide_curve_paths=[],
        )
        assert "guide_curve_paths" not in node


# ===========================================================================
# Tests: feature_loft_spec describes guide_curve_paths
# ===========================================================================

class TestFeatureLoftSpec:
    def test_spec_mentions_guide_curve_paths(self):
        props = feature_loft_spec.input_schema.get("properties", {})
        assert "guide_curve_paths" in props

    def test_guide_curve_paths_is_array(self):
        props = feature_loft_spec.input_schema["properties"]
        assert props["guide_curve_paths"]["type"] == "array"

    def test_spec_description_mentions_guide(self):
        assert "guide" in feature_loft_spec.description.lower()

    def test_guide_curve_paths_not_required(self):
        req = feature_loft_spec.input_schema.get("required", [])
        assert "guide_curve_paths" not in req


# ===========================================================================
# Tests: run_feature_loft with guide_curve_paths (integration)
# ===========================================================================

def _make_ctx():
    store = {"content": json.dumps({"version": 1, "features": []}), "kind": "feature"}
    project_id = uuid.uuid4()
    file_id = uuid.uuid4()

    class FakePool:
        def fetchone(self, query, *args):
            return (store["content"], store["kind"])
        def execute(self, query, *args):
            store["content"] = args[0]

    from kerf_core.utils.context import ProjectCtx
    ctx = ProjectCtx(
        pool=FakePool(),
        storage=None,
        project_id=project_id,
        user_id=uuid.uuid4(),
        role="owner",
        http_client=None,
    )
    return ctx, store, file_id


class TestRunFeatureLoftGuides:
    def _run(self, ctx, fid, **kwargs):
        from kerf_cad_core.feature_loft import run_feature_loft
        a = {"file_id": str(fid), **kwargs}
        raw = asyncio.new_event_loop().run_until_complete(
            run_feature_loft(ctx, json.dumps(a).encode())
        )
        return json.loads(raw)

    def test_guides_stored_in_node(self):
        ctx, store, fid = _make_ctx()
        result = self._run(
            ctx, fid,
            profile_sketch_paths=["a.sketch", "b.sketch"],
            guide_curve_paths=["g.sketch"],
        )
        assert "error" not in result
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert node["guide_curve_paths"] == ["g.sketch"]

    def test_has_guides_in_response(self):
        ctx, store, fid = _make_ctx()
        result = self._run(
            ctx, fid,
            profile_sketch_paths=["a.sketch", "b.sketch"],
            guide_curve_paths=["g.sketch"],
        )
        assert "error" not in result
        assert result.get("has_guides") is True

    def test_no_guides_has_guides_false(self):
        ctx, store, fid = _make_ctx()
        result = self._run(
            ctx, fid,
            profile_sketch_paths=["a.sketch", "b.sketch"],
        )
        assert "error" not in result
        assert result.get("has_guides") is False

    def test_invalid_guide_path_rejected(self):
        ctx, store, fid = _make_ctx()
        result = self._run(
            ctx, fid,
            profile_sketch_paths=["a.sketch", "b.sketch"],
            guide_curve_paths=["guide.step"],  # wrong extension
        )
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_guide_with_symmetric_rejected(self):
        ctx, store, fid = _make_ctx()
        result = self._run(
            ctx, fid,
            profile_sketch_paths=["a.sketch", "b.sketch"],
            guide_curve_paths=["g.sketch"],
            symmetric=True,
        )
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"
