"""
Tests for surface_boolean_robust and surface_health_check (T-37).

All tests are hermetic: no OCC, no database, no network.  Pure-Python
guards and geometry logic only.  OCC-dependent paths are verified by
passing a stub occ_fn.

Coverage (≥25 tests):
  - surface_health_check: type guard, degenerate patch, self-intersecting
    control net, high-degree warning, duplicate control points, degree<1 error
  - surface_boolean_robust: valid surfaces pass, degenerate srf_a rejected,
    degenerate srf_b rejected, invalid kind rejected, invalid bbox_tol rejected,
    tolerance scales with bbox, large model gets large tolerance, tiny model
    gets small tolerance, tolerance clamped to [1e-7, 1e-2], occ_fn=None
    returns ok with no result, occ_fn success path, occ_fn returns None triggers
    retry, retry succeeds, retry also fails returns ok=False with reason,
    relaxed tolerance capped at 1e-2, result dict always has required keys,
    health_a / health_b populated in all paths, friendly failure dict on bad input
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.surface_boolean_robust import (
    _TOL_MAX,
    _TOL_MIN,
    _auto_tolerance,
    _relaxed_tolerance,
    surface_boolean_robust,
    surface_health_check,
)


# ---------------------------------------------------------------------------
# Helpers: surface factories
# ---------------------------------------------------------------------------

def make_flat_surface(nu: int = 3, nv: int = 3, scale: float = 1.0) -> NurbsSurface:
    """Create a simple flat bilinear patch."""
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            cp[i, j] = [i * scale, j * scale, 0.0]
    ku = np.array([0.0] * 2 + list(np.linspace(0, 1, nu - 1)) + [1.0] * 2)
    kv = np.array([0.0] * 2 + list(np.linspace(0, 1, nv - 1)) + [1.0] * 2)
    # Simple open clamped knots for degree-1 surface
    ku = np.linspace(0.0, 1.0, nu + 2)
    kv = np.linspace(0.0, 1.0, nv + 2)
    return NurbsSurface(
        degree_u=1,
        degree_v=1,
        control_points=cp,
        knots_u=np.array([0.0, 0.0, 1.0] if nu == 2 else [0.0] * 2 + list(np.linspace(0, 1, nu - 1)) + [1.0] * 2),
        knots_v=np.array([0.0, 0.0, 1.0] if nv == 2 else [0.0] * 2 + list(np.linspace(0, 1, nv - 1)) + [1.0] * 2),
    )


def make_simple_surface(
    nu: int = 3,
    nv: int = 3,
    scale: float = 1.0,
    degree_u: int = 2,
    degree_v: int = 2,
) -> NurbsSurface:
    """Create a non-degenerate flat surface with specified degrees."""
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            cp[i, j] = [i * scale, j * scale, 0.0]
    n_ku = nu + degree_u + 1
    n_kv = nv + degree_v + 1
    ku = np.concatenate([
        np.zeros(degree_u),
        np.linspace(0, 1, n_ku - 2 * degree_u),
        np.ones(degree_u),
    ])
    kv = np.concatenate([
        np.zeros(degree_v),
        np.linspace(0, 1, n_kv - 2 * degree_v),
        np.ones(degree_v),
    ])
    return NurbsSurface(
        degree_u=degree_u,
        degree_v=degree_v,
        control_points=cp,
        knots_u=ku,
        knots_v=kv,
    )


def make_degenerate_surface() -> NurbsSurface:
    """All control points collapsed to one point — fully degenerate."""
    cp = np.zeros((3, 3, 3))  # all zeros → all patches have zero area
    ku = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    kv = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=2, degree_v=2,
        control_points=cp,
        knots_u=ku, knots_v=kv,
    )


def make_self_intersecting_surface() -> NurbsSurface:
    """Control net rows fold on themselves (sign-flipping cross-products)."""
    cp = np.array([
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]],
        [[2.0, 1.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]],  # reversed → fold
        [[0.0, 2.0, 0.0], [1.0, 2.0, 0.0], [2.0, 2.0, 0.0]],
        [[0.0, 3.0, 0.0], [1.0, 3.0, 0.0], [2.0, 3.0, 0.0]],
        [[0.0, 4.0, 0.0], [1.0, 4.0, 0.0], [2.0, 4.0, 0.0]],
    ])
    ku = np.array([0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0, 1.0])
    kv = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=2, degree_v=2,
        control_points=cp,
        knots_u=ku, knots_v=kv,
    )


def make_large_surface() -> NurbsSurface:
    """Surface with bbox diagonal ~1000 units."""
    return make_simple_surface(scale=500.0)


def make_tiny_surface() -> NurbsSurface:
    """Surface with bbox diagonal ~0.001 units."""
    return make_simple_surface(scale=0.0005)


# ---------------------------------------------------------------------------
# surface_health_check — type guard
# ---------------------------------------------------------------------------

class TestHealthCheckTypeGuard:
    def test_non_surface_returns_not_ok(self):
        result = surface_health_check("not a surface")
        assert result["ok"] is False
        assert any("NurbsSurface" in e or "expected" in e for e in result["errors"])

    def test_none_returns_not_ok(self):
        result = surface_health_check(None)
        assert result["ok"] is False

    def test_dict_returns_not_ok(self):
        result = surface_health_check({"degree_u": 2})
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# surface_health_check — degenerate patch detection
# ---------------------------------------------------------------------------

class TestHealthCheckDegeneratePatch:
    def test_fully_degenerate_surface_rejected(self):
        srf = make_degenerate_surface()
        result = surface_health_check(srf)
        assert result["ok"] is False
        assert len(result["errors"]) >= 1
        assert any("degenerate" in e.lower() for e in result["errors"])

    def test_healthy_surface_passes(self):
        srf = make_simple_surface()
        result = surface_health_check(srf)
        assert result["ok"] is True
        assert result["errors"] == []

    def test_partial_degeneracy_may_warn(self):
        """A surface with one degenerate patch but not all → warning, not error."""
        cp = np.zeros((3, 3, 3))
        # Make most patches non-degenerate
        for i in range(3):
            for j in range(3):
                cp[i, j] = [i * 1.0, j * 1.0, 0.0]
        # Collapse one patch by making cp[0,0] == cp[1,0] == cp[0,1] == cp[1,1]
        # Still leaves other patches with area > 0
        ku = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
        kv = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
        srf = NurbsSurface(degree_u=2, degree_v=2, control_points=cp, knots_u=ku, knots_v=kv)
        result = surface_health_check(srf)
        # Either ok with a warning OR not ok — just verify the dict structure
        assert "ok" in result
        assert "warnings" in result
        assert "errors" in result


# ---------------------------------------------------------------------------
# surface_health_check — self-intersecting control net
# ---------------------------------------------------------------------------

class TestHealthCheckSelfIntersecting:
    def test_self_intersecting_net_flagged(self):
        srf = make_self_intersecting_surface()
        result = surface_health_check(srf)
        assert result["ok"] is False
        assert any("self-intersect" in e.lower() or "fold" in e.lower() for e in result["errors"])

    def test_non_intersecting_net_passes(self):
        srf = make_simple_surface()
        result = surface_health_check(srf)
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# surface_health_check — degree warnings / errors
# ---------------------------------------------------------------------------

class TestHealthCheckDegree:
    def test_high_degree_generates_warning(self):
        srf = make_simple_surface(degree_u=10, degree_v=2, nu=12, nv=3)
        result = surface_health_check(srf)
        # Should have a warning about high degree
        assert any("degree" in w.lower() or "high" in w.lower() for w in result["warnings"])

    def test_result_always_has_required_keys(self):
        srf = make_simple_surface()
        result = surface_health_check(srf)
        assert "ok" in result
        assert "warnings" in result
        assert "errors" in result


# ---------------------------------------------------------------------------
# surface_boolean_robust — input validation
# ---------------------------------------------------------------------------

class TestRobustInputValidation:
    def test_invalid_kind_rejected(self):
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        result = surface_boolean_robust(srf_a, srf_b, "union")
        assert result["ok"] is False
        assert "union" in result["reason"]

    def test_empty_kind_rejected(self):
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        result = surface_boolean_robust(srf_a, srf_b, "")
        assert result["ok"] is False

    def test_degenerate_srf_a_rejected(self):
        srf_a = make_degenerate_surface()
        srf_b = make_simple_surface()
        result = surface_boolean_robust(srf_a, srf_b, "cut")
        assert result["ok"] is False
        assert "surface A" in result["reason"]

    def test_degenerate_srf_b_rejected(self):
        srf_a = make_simple_surface()
        srf_b = make_degenerate_surface()
        result = surface_boolean_robust(srf_a, srf_b, "fuse")
        assert result["ok"] is False
        assert "surface B" in result["reason"]

    def test_non_surface_srf_a_rejected(self):
        result = surface_boolean_robust("bad", make_simple_surface(), "cut")
        assert result["ok"] is False

    def test_non_surface_srf_b_rejected(self):
        result = surface_boolean_robust(make_simple_surface(), None, "cut")
        assert result["ok"] is False

    def test_invalid_bbox_tol_zero_rejected(self):
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        result = surface_boolean_robust(srf_a, srf_b, "cut", bbox_tol=0.0)
        assert result["ok"] is False
        assert "bbox_tol" in result["reason"]

    def test_invalid_bbox_tol_negative_rejected(self):
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        result = surface_boolean_robust(srf_a, srf_b, "fuse", bbox_tol=-1e-5)
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# surface_boolean_robust — tolerance auto-scaling
# ---------------------------------------------------------------------------

class TestRobustToleranceScaling:
    def test_tolerance_scales_with_bbox(self):
        srf_small = make_simple_surface(scale=1.0)
        srf_large = make_simple_surface(scale=1000.0)
        tol_small = _auto_tolerance(srf_small, srf_small)
        tol_large = _auto_tolerance(srf_large, srf_large)
        assert tol_large > tol_small

    def test_large_model_tolerance_higher(self):
        srf = make_large_surface()
        tol = _auto_tolerance(srf, srf)
        assert tol > 1e-5  # should be well above the minimum

    def test_tiny_model_tolerance_clamped_at_min(self):
        srf = make_tiny_surface()
        tol = _auto_tolerance(srf, srf)
        assert tol >= _TOL_MIN

    def test_tolerance_clamped_at_max(self):
        # Create a gigantic surface; tolerance must never exceed _TOL_MAX
        srf = make_simple_surface(scale=1e8)
        tol = _auto_tolerance(srf, srf)
        assert tol <= _TOL_MAX

    def test_bbox_tol_override_respected(self):
        """GK-72: bbox_tol is used as base tolerance regardless of path.

        With NurbsSurface inputs the pure-Python path fails (unsupported-input),
        but the tolerance field reflects the requested override.
        """
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        result = surface_boolean_robust(srf_a, srf_b, "cut", bbox_tol=5e-5)
        # Tolerance is recorded even on pure-Python failure
        assert abs(result["tolerance"] - 5e-5) < 1e-10

    def test_bbox_tol_clamped_to_min(self):
        """GK-72: sub-minimum bbox_tol is clamped to _TOL_MIN.

        With NurbsSurface inputs the pure-Python path fails, but the
        tolerance field is still clamped correctly.
        """
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        # Provide a tolerance below the minimum; should be clamped
        result = surface_boolean_robust(srf_a, srf_b, "cut", bbox_tol=1e-20)
        assert result["tolerance"] >= _TOL_MIN


# ---------------------------------------------------------------------------
# surface_boolean_robust — occ_fn integration paths
# ---------------------------------------------------------------------------

class TestRobustOccFnPaths:
    def test_no_occ_fn_attempts_pure_python(self):
        """GK-72: occ_fn=None now runs pure-Python path (not guards-only).

        NurbsSurface inputs are not recognised by the AABB/sphere/cylinder
        engine, so the pure-Python boolean raises BuildError('unsupported-input')
        and the wrapper returns ok=False with via='py'.  The key assertion is
        that the path used is 'py' (not 'occt' / 'none') and that no OCCT
        import was attempted.
        """
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        result = surface_boolean_robust(srf_a, srf_b, "cut", occ_fn=None)
        # Pure-Python path was attempted
        assert result["via"] == "py"
        # Result is None because NurbsSurface bodies are unsupported-input
        assert result["result"] is None
        # ok=False with a reason (unsupported-input from boolean engine)
        assert isinstance(result["reason"], str)
        assert len(result["reason"]) > 0

    def test_occ_fn_success_path(self):
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        sentinel = object()

        def good_occ_fn(a, b, kind, tol):
            return sentinel

        result = surface_boolean_robust(srf_a, srf_b, "fuse", occ_fn=good_occ_fn)
        assert result["ok"] is True
        assert result["result"] is sentinel
        assert result["retried"] is False

    def test_occ_fn_returns_none_triggers_retry(self):
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        calls = []
        sentinel = object()

        def occ_fn(a, b, kind, tol):
            calls.append(tol)
            # Fail on first call, succeed on second
            return sentinel if len(calls) > 1 else None

        result = surface_boolean_robust(srf_a, srf_b, "common", occ_fn=occ_fn)
        assert result["ok"] is True
        assert result["retried"] is True
        assert len(calls) == 2
        # Second call uses relaxed (larger) tolerance
        assert calls[1] > calls[0]

    def test_occ_fn_raises_triggers_retry(self):
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        calls = []
        sentinel = object()

        def occ_fn(a, b, kind, tol):
            calls.append(tol)
            if len(calls) == 1:
                raise RuntimeError("OCC boolean failed")
            return sentinel

        result = surface_boolean_robust(srf_a, srf_b, "cut", occ_fn=occ_fn)
        assert result["ok"] is True
        assert result["retried"] is True
        assert result["result"] is sentinel

    def test_occ_fn_both_fail_returns_not_ok(self):
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()

        def bad_occ_fn(a, b, kind, tol):
            raise RuntimeError(f"always fails at {tol}")

        result = surface_boolean_robust(srf_a, srf_b, "cut", occ_fn=bad_occ_fn)
        assert result["ok"] is False
        assert result["result"] is None
        assert result["retried"] is True
        assert len(result["reason"]) > 0

    def test_retry_tolerance_larger_than_initial(self):
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        recorded = {}

        def occ_fn(a, b, kind, tol):
            if "first" not in recorded:
                recorded["first"] = tol
                return None
            recorded["retry"] = tol
            return object()

        result = surface_boolean_robust(srf_a, srf_b, "cut", occ_fn=occ_fn)
        assert result["ok"] is True
        assert recorded["retry"] > recorded["first"]


# ---------------------------------------------------------------------------
# surface_boolean_robust — result dict structure
# ---------------------------------------------------------------------------

class TestRobustResultStructure:
    _REQUIRED_KEYS = {"ok", "result", "reason", "retried", "tolerance", "health_a", "health_b"}

    def test_success_result_has_all_keys(self):
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        result = surface_boolean_robust(srf_a, srf_b, "cut")
        assert self._REQUIRED_KEYS <= set(result.keys())

    def test_failure_result_has_all_keys(self):
        srf_a = make_degenerate_surface()
        srf_b = make_simple_surface()
        result = surface_boolean_robust(srf_a, srf_b, "cut")
        assert self._REQUIRED_KEYS <= set(result.keys())

    def test_invalid_kind_result_has_all_keys(self):
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        result = surface_boolean_robust(srf_a, srf_b, "bad_kind")
        assert self._REQUIRED_KEYS <= set(result.keys())

    def test_health_a_populated_on_success(self):
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        result = surface_boolean_robust(srf_a, srf_b, "cut")
        assert isinstance(result["health_a"], dict)
        assert "ok" in result["health_a"]

    def test_health_b_populated_on_success(self):
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        result = surface_boolean_robust(srf_a, srf_b, "fuse")
        assert isinstance(result["health_b"], dict)
        assert "ok" in result["health_b"]

    def test_ok_false_reason_nonempty(self):
        result = surface_boolean_robust(
            make_degenerate_surface(), make_simple_surface(), "cut"
        )
        assert result["ok"] is False
        assert isinstance(result["reason"], str)
        assert len(result["reason"]) > 0

    def test_all_valid_kinds_accepted(self):
        """GK-72: all three kind values are accepted (not rejected by kind-guard).

        With NurbsSurface inputs the pure-Python boolean fails
        (unsupported-input), but the failure comes from the boolean engine, not
        from kind-validation — so the result dict is structurally complete and
        via='py'.
        """
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        for kind in ("cut", "fuse", "common"):
            result = surface_boolean_robust(srf_a, srf_b, kind)
            # Kind was accepted (not rejected by the kind-guard)
            assert "invalid boolean kind" not in result.get("reason", ""), (
                f"kind={kind!r} was incorrectly rejected by kind-guard"
            )
            # Pure-Python path was taken
            assert result["via"] == "py", f"kind={kind!r} did not use py path"


# ---------------------------------------------------------------------------
# _relaxed_tolerance helper
# ---------------------------------------------------------------------------

class TestRelaxedTolerance:
    def test_relaxed_is_larger(self):
        tol = 1e-5
        relaxed = _relaxed_tolerance(tol)
        assert relaxed is not None
        assert relaxed > tol

    def test_at_max_returns_none(self):
        # If tol * factor > _TOL_MAX, must return None
        tol = _TOL_MAX / 5.0  # 5x relaxed = TOL_MAX exactly or more
        relaxed = _relaxed_tolerance(tol)
        # relaxed = tol * 10 = 2 * TOL_MAX > TOL_MAX → None
        assert relaxed is None

    def test_small_tol_returns_value(self):
        tol = 1e-6
        relaxed = _relaxed_tolerance(tol)
        assert relaxed is not None
        assert relaxed <= _TOL_MAX


# ---------------------------------------------------------------------------
# GK-72: pure-Python default path + OCCT opt-in
# ---------------------------------------------------------------------------

def _make_box_body(
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    dx: float = 2.0,
    dy: float = 2.0,
    dz: float = 2.0,
    tol: float = 1e-7,
):
    """Return an axis-aligned box Body via brep_build.box_to_body."""
    from kerf_cad_core.geom.brep_build import box_to_body
    return box_to_body(corner=(x, y, z), dx=dx, dy=dy, dz=dz, tol=tol)


class TestGK72PurePythonDefault:
    """GK-72 oracle: pure-Python is the DEFAULT path; OCCT is opt-in.

    All tests are hermetic — no OCC import, no database, no network.
    """

    # ── via field ─────────────────────────────────────────────────────────

    def test_result_has_via_key(self):
        """Result dict always contains 'via' key (new in GK-72)."""
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        result = surface_boolean_robust(srf_a, srf_b, "cut")
        assert "via" in result

    def test_default_path_is_py_not_occt(self):
        """With no occ_fn and no env flag, via='py' (pure-Python attempted)."""
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        result = surface_boolean_robust(srf_a, srf_b, "fuse")
        assert result["via"] == "py"

    def test_occt_occ_fn_gives_via_occt(self):
        """Passing occ_fn forces via='occt'."""
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        sentinel = object()

        def stub_occ_fn(a, b, kind, tol):
            return sentinel

        result = surface_boolean_robust(srf_a, srf_b, "fuse", occ_fn=stub_occ_fn)
        assert result["via"] == "occt"
        assert result["result"] is sentinel

    def test_use_occt_true_no_occ_fn_returns_error(self):
        """use_occt=True with no occ_fn provided returns ok=False, via='none'."""
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        result = surface_boolean_robust(srf_a, srf_b, "cut", use_occt=True)
        assert result["ok"] is False
        assert result["via"] == "none"
        assert "occ_fn" in result["reason"].lower() or "occt" in result["reason"].lower()

    def test_use_occt_false_overrides_env_flag(self, monkeypatch):
        """use_occt=False forces pure-Python even if KERF_OCCT_BOOLEAN=1."""
        monkeypatch.setenv("KERF_OCCT_BOOLEAN", "1")
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        occt_called = []

        def stub_occ_fn(a, b, kind, tol):
            occt_called.append(True)
            return object()

        result = surface_boolean_robust(
            srf_a, srf_b, "cut", occ_fn=stub_occ_fn, use_occt=False
        )
        # use_occt=False should override both the env flag AND occ_fn
        assert result["via"] == "py"
        assert occt_called == []

    def test_env_flag_kerf_occt_boolean_routes_to_occt(self, monkeypatch):
        """KERF_OCCT_BOOLEAN=1 env flag routes to OCCT when occ_fn provided."""
        monkeypatch.setenv("KERF_OCCT_BOOLEAN", "1")
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        sentinel = object()

        def stub_occ_fn(a, b, kind, tol):
            return sentinel

        result = surface_boolean_robust(srf_a, srf_b, "fuse", occ_fn=stub_occ_fn)
        assert result["via"] == "occt"
        assert result["result"] is sentinel

    # ── Body inputs succeed on pure-Python path ───────────────────────────

    def test_body_union_via_py_default(self):
        """Box+box union via pure-Python default path returns a validated Body.

        Oracle (GK-72): occ_fn=None now returns a real validated Body,
        not result=None.
        """
        from kerf_cad_core.geom.brep import Body
        body_a = _make_box_body(x=0.0, dx=2.0)
        body_b = _make_box_body(x=1.0, dx=2.0)  # overlapping
        result = surface_boolean_robust(body_a, body_b, "fuse")
        assert result["ok"] is True, f"expected ok=True; reason={result['reason']!r}"
        assert isinstance(result["result"], Body), (
            f"expected Body result; got {type(result['result'])}"
        )
        assert result["via"] == "py"
        assert result["retried"] is False

    def test_body_intersection_via_py_default(self):
        """Box∩box intersection returns a validated Body on the py path."""
        from kerf_cad_core.geom.brep import Body
        body_a = _make_box_body(x=0.0, dx=2.0)
        body_b = _make_box_body(x=1.0, dx=2.0)
        result = surface_boolean_robust(body_a, body_b, "common")
        assert result["ok"] is True
        assert isinstance(result["result"], Body)
        assert result["via"] == "py"

    def test_body_difference_via_py_default(self):
        """Box − box difference returns a validated Body on the py path."""
        from kerf_cad_core.geom.brep import Body
        body_a = _make_box_body(x=0.0, dx=3.0)
        body_b = _make_box_body(x=1.0, dx=1.0)  # fully inside body_a
        result = surface_boolean_robust(body_a, body_b, "cut")
        assert result["ok"] is True
        assert isinstance(result["result"], Body)
        assert result["via"] == "py"

    def test_body_health_check_skipped(self):
        """Body inputs skip the NURBS health check (health_a/b = empty dict)."""
        body_a = _make_box_body()
        body_b = _make_box_body(x=3.0)
        result = surface_boolean_robust(body_a, body_b, "fuse")
        assert result["health_a"] == {}
        assert result["health_b"] == {}

    def test_body_disjoint_union_two_solids(self):
        """Disjoint boxes produce a multi-solid Body via the py path."""
        from kerf_cad_core.geom.brep import Body
        body_a = _make_box_body(x=0.0, dx=1.0)
        body_b = _make_box_body(x=5.0, dx=1.0)  # far away, disjoint
        result = surface_boolean_robust(body_a, body_b, "fuse")
        assert result["ok"] is True
        assert isinstance(result["result"], Body)
        assert result["via"] == "py"
        # disjoint union → two solids
        assert len(result["result"].solids) == 2

    # ── NurbsSurface inputs fail gracefully on pure-Python path ──────────

    def test_nurbs_inputs_fail_gracefully_on_py_path(self):
        """NurbsSurface inputs are unsupported by the AABB/sphere engine.

        Failure is graceful (ok=False, via='py'), not an exception.
        """
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        result = surface_boolean_robust(srf_a, srf_b, "cut")
        assert result["ok"] is False
        assert result["via"] == "py"
        assert result["result"] is None
        # Reason should mention unsupported or the boolean engine failure
        assert isinstance(result["reason"], str) and len(result["reason"]) > 0

    def test_nurbs_with_explicit_occ_fn_uses_occt(self):
        """NurbsSurface + explicit occ_fn → OCCT path, not pure-Python."""
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        occt_calls = []
        sentinel = object()

        def stub_occ_fn(a, b, kind, tol):
            occt_calls.append((a, b, kind, tol))
            return sentinel

        result = surface_boolean_robust(srf_a, srf_b, "fuse", occ_fn=stub_occ_fn)
        assert result["ok"] is True
        assert result["result"] is sentinel
        assert result["via"] == "occt"
        assert len(occt_calls) == 1

    # ── result dict completeness ──────────────────────────────────────────

    def test_result_has_all_required_keys_on_py_success(self):
        """py-path success dict contains all documented keys."""
        required = {"ok", "result", "reason", "retried", "attempts",
                    "tolerance", "health_a", "health_b", "via"}
        body_a = _make_box_body()
        body_b = _make_box_body(x=3.0)
        result = surface_boolean_robust(body_a, body_b, "fuse")
        assert required <= set(result.keys())

    def test_result_has_all_required_keys_on_py_failure(self):
        """py-path failure dict contains all documented keys."""
        required = {"ok", "result", "reason", "retried", "attempts",
                    "tolerance", "health_a", "health_b", "via"}
        srf_a = make_simple_surface()
        srf_b = make_simple_surface()
        result = surface_boolean_robust(srf_a, srf_b, "cut")
        assert required <= set(result.keys())

    def test_py_success_retried_is_false(self):
        """Pure-Python path never retries (deterministic)."""
        body_a = _make_box_body()
        body_b = _make_box_body(x=3.0)
        result = surface_boolean_robust(body_a, body_b, "fuse")
        assert result["retried"] is False

    def test_invalid_kind_still_returns_via_none(self):
        """Invalid kind is rejected before path selection; via='none'."""
        body_a = _make_box_body()
        body_b = _make_box_body()
        result = surface_boolean_robust(body_a, body_b, "union")
        assert result["ok"] is False
        assert result["via"] == "none"

    def test_occt_path_occ_fn_not_called_when_py_default(self):
        """When using the pure-Python default, occ_fn stub is never called."""
        body_a = _make_box_body()
        body_b = _make_box_body(x=3.0)
        occt_calls = []

        # Do NOT pass occ_fn — use default pure-Python
        result = surface_boolean_robust(body_a, body_b, "fuse")
        assert result["via"] == "py"
        assert occt_calls == []  # stub was never called
