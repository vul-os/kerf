"""test_export_3dm.py — pytest suite for export_3dm.py

Structure
---------
1. Pure-Python serialisation-prep tests (no rhino3dm required):
   - build_nurbs_curve_payload / parse_nurbs_curve_payload round-trip
   - build_nurbs_surface_payload / parse_nurbs_surface_payload round-trip
   - Weight/validation edge cases

2. rhino3dm-gated tests (skipped cleanly when rhino3dm unavailable):
   - NURBS curve export → reimport: control-point nets identical to 1e-9
   - NURBS surface export → reimport: control-point nets identical to 1e-9
   - Rational NURBS curve round-trip (non-unit weights)
   - Rational NURBS surface round-trip
   - Mixed-object export (curve + surface + point) produces a parseable .3dm
   - export_to_3dm raises ImportError when rhino3dm absent (mock)
   - export_to_3dm raises ValueError for empty object list

ANALYTIC ORACLE
---------------
The round-trip oracle is closed-form: we build a NURBS object from known
control points, export to .3dm, reimport via rhino3dm, and assert that every
control-point coordinate matches the original to within 1e-9 (Euclidean
absolute tolerance in each axis).
"""

from __future__ import annotations

import importlib
import math
import sys
import types
import unittest
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Import the module under test (no rhino3dm required for the module itself)
# ---------------------------------------------------------------------------

from kerf_imports.export_3dm import (
    build_nurbs_curve_payload,
    build_nurbs_surface_payload,
    export_to_3dm,
    parse_nurbs_curve_payload,
    parse_nurbs_surface_payload,
    _read_3dm_objects,
    _extract_nurbs_curve_cps,
    _extract_nurbs_surface_cps,
)

# Marker used to skip rhino3dm-dependent tests when the library is absent.
# NOTE: this is a lazy check — we don't call pytest.importorskip at module
# level so that the pure-Python tests always run.
_RHINO3DM_AVAILABLE = pytest.mark.skipif(
    __import__("importlib").util.find_spec("rhino3dm") is None,
    reason="rhino3dm not installed",
)

# ---------------------------------------------------------------------------
# Tolerance for round-trip oracle
# ---------------------------------------------------------------------------

_TOL = 1e-9


def _assert_cps_equal(
    expected: list[list[float]],
    actual: list[list[float]],
    tol: float = _TOL,
    label: str = "",
) -> None:
    """Assert two lists of [x,y,z] control points are equal within *tol*."""
    prefix = f"{label}: " if label else ""
    assert len(expected) == len(actual), (
        f"{prefix}control-point count mismatch: {len(expected)} vs {len(actual)}"
    )
    for i, (e, a) in enumerate(zip(expected, actual)):
        for axis, (ev, av) in enumerate(zip(e, a)):
            diff = abs(ev - av)
            assert diff <= tol, (
                f"{prefix}CP[{i}][{axis}]: expected {ev:.18g}, got {av:.18g}, "
                f"delta={diff:.3e} > tol={tol:.3e}"
            )


def _assert_surface_cps_equal(
    expected: list[list[list[float]]],
    actual: list[list[list[float]]],
    tol: float = _TOL,
    label: str = "",
) -> None:
    prefix = f"{label}: " if label else ""
    assert len(expected) == len(actual), (
        f"{prefix}u-count mismatch: {len(expected)} vs {len(actual)}"
    )
    for i, (er, ar) in enumerate(zip(expected, actual)):
        assert len(er) == len(ar), (
            f"{prefix}v-count at u={i}: {len(er)} vs {len(ar)}"
        )
        for j, (e, a) in enumerate(zip(er, ar)):
            for axis, (ev, av) in enumerate(zip(e, a)):
                diff = abs(ev - av)
                assert diff <= tol, (
                    f"{prefix}CP[{i},{j}][{axis}]: expected {ev:.18g}, "
                    f"got {av:.18g}, delta={diff:.3e} > tol={tol:.3e}"
                )


# ===========================================================================
# 1. Pure-Python serialisation-prep tests (no rhino3dm)
# ===========================================================================

class TestBuildNurbsCurvePayload:

    def test_basic_quadratic(self):
        """Degree-2 open NURBS curve, 3 CPs, uniform knots."""
        degree = 2
        # rhino3dm knot convention: n + degree - 1 = 3 + 2 - 1 = 4 knots
        knots = [0.0, 0.0, 1.0, 1.0]
        cps = [[0.0, 0.0, 0.0], [1.0, 1.0, 0.0], [2.0, 0.0, 0.0]]
        payload = build_nurbs_curve_payload(degree, knots, cps)

        assert payload["source"] == "kerf"
        assert payload["kind"] == "sketch"
        nc = payload["nurbs_curve"]
        assert nc["degree"] == 2
        assert len(nc["knots"]) == 4
        assert len(nc["control_points"]) == 3
        assert len(nc["weights"]) == 3
        assert all(abs(w - 1.0) < 1e-15 for w in nc["weights"])

    def test_rational_weights_preserved(self):
        degree = 2
        knots = [0.0, 0.0, 1.0, 1.0]
        cps = [[0.0, 0.0, 0.0], [1.0, 1.0, 0.0], [2.0, 0.0, 0.0]]
        weights = [1.0, 0.7071067811865476, 1.0]  # 1/sqrt(2) for quarter-arc
        payload = build_nurbs_curve_payload(degree, knots, cps, weights)
        nc = payload["nurbs_curve"]
        assert abs(nc["weights"][1] - 0.7071067811865476) < 1e-15

    def test_weight_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="weights length"):
            build_nurbs_curve_payload(
                1, [0.0, 1.0], [[0, 0, 0], [1, 0, 0]], weights=[1.0]
            )

    def test_float_coercion(self):
        """Integer inputs should be coerced to float."""
        payload = build_nurbs_curve_payload(
            1, [0, 1], [[0, 0, 0], [1, 0, 0]]
        )
        nc = payload["nurbs_curve"]
        assert isinstance(nc["knots"][0], float)
        assert isinstance(nc["control_points"][0][0], float)


class TestParsNurbsCurvePayload:

    def test_round_trip(self):
        cps = [[0.0, 0.0, 0.0], [1.0, 2.0, 3.0], [4.0, 0.0, 1.0]]
        knots = [0.0, 0.0, 0.5, 1.0, 1.0]
        payload = build_nurbs_curve_payload(3, knots, cps)
        parsed = parse_nurbs_curve_payload(payload)

        assert parsed["degree"] == 3
        for i, (orig, back) in enumerate(zip(cps, parsed["control_points"])):
            for axis in range(3):
                assert abs(orig[axis] - back[axis]) < 1e-15, (
                    f"CP[{i}][{axis}] round-trip mismatch"
                )

    def test_missing_nurbs_curve_key_raises(self):
        with pytest.raises(KeyError):
            parse_nurbs_curve_payload({})

    def test_default_weights(self):
        """parse_nurbs_curve_payload fills missing weights with 1.0."""
        payload = {
            "nurbs_curve": {
                "degree": 1,
                "knots": [0.0, 1.0],
                "control_points": [[0, 0, 0], [1, 0, 0]],
                # no "weights" key
            }
        }
        parsed = parse_nurbs_curve_payload(payload)
        assert parsed["weights"] == [1.0, 1.0]


class TestBuildNurbsSurfacePayload:

    def _flat_surface_cps(self) -> list[list[list[float]]]:
        """2x2 flat surface in XY plane."""
        return [
            [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            [[1.0, 0.0, 0.0], [1.0, 1.0, 0.0]],
        ]

    def test_basic_bilinear(self):
        cps = self._flat_surface_cps()
        # degree_u=1,degree_v=1 → knots_u: n_u+degree_u-1 = 2+1-1 = 2 knots
        knots_u = [0.0, 1.0]
        knots_v = [0.0, 1.0]
        payload = build_nurbs_surface_payload(1, 1, knots_u, knots_v, cps)

        assert payload["source"] == "kerf"
        assert payload["kind"] == "surf"
        ns = payload["nurbs_surface"]
        assert ns["degree_u"] == 1
        assert ns["degree_v"] == 1
        assert len(ns["knots_u"]) == 2
        assert len(ns["knots_v"]) == 2
        assert len(ns["control_points"]) == 2
        assert len(ns["control_points"][0]) == 2
        assert len(ns["weights"]) == 2
        assert all(abs(w - 1.0) < 1e-15 for row in ns["weights"] for w in row)

    def test_rational_weights_preserved(self):
        cps = self._flat_surface_cps()
        weights = [[1.0, 0.5], [0.5, 1.0]]
        payload = build_nurbs_surface_payload(1, 1, [0.0, 1.0], [0.0, 1.0], cps, weights)
        ns = payload["nurbs_surface"]
        assert abs(ns["weights"][0][1] - 0.5) < 1e-15
        assert abs(ns["weights"][1][0] - 0.5) < 1e-15


class TestParseNurbsSurfacePayload:

    def test_round_trip(self):
        cps = [
            [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 2.0, 0.0]],
            [[1.0, 0.0, 0.5], [1.0, 1.0, 0.5], [1.0, 2.0, 0.5]],
        ]
        knots_u = [0.0, 1.0]
        knots_v = [0.0, 0.5, 1.0]
        payload = build_nurbs_surface_payload(1, 2, knots_u, knots_v, cps)
        parsed = parse_nurbs_surface_payload(payload)

        assert parsed["degree_u"] == 1
        assert parsed["degree_v"] == 2
        for i in range(2):
            for j in range(3):
                for axis in range(3):
                    assert abs(cps[i][j][axis] - parsed["control_points"][i][j][axis]) < 1e-15

    def test_missing_nurbs_surface_key_raises(self):
        with pytest.raises(KeyError):
            parse_nurbs_surface_payload({})

    def test_default_weights(self):
        payload = {
            "nurbs_surface": {
                "degree_u": 1,
                "degree_v": 1,
                "knots_u": [0.0, 1.0],
                "knots_v": [0.0, 1.0],
                "control_points": [
                    [[0, 0, 0], [0, 1, 0]],
                    [[1, 0, 0], [1, 1, 0]],
                ],
            }
        }
        parsed = parse_nurbs_surface_payload(payload)
        assert all(abs(w - 1.0) < 1e-15 for row in parsed["weights"] for w in row)


# ===========================================================================
# 2. rhino3dm-gated round-trip tests
# ===========================================================================
# Each class below is decorated with @_RHINO3DM_AVAILABLE so individual tests
# are skipped cleanly when rhino3dm is not installed, while the pure-Python
# tests above always run.


@_RHINO3DM_AVAILABLE
class TestExport3dmValueError:
    """ValueError on empty input — no rhino3dm I/O needed but rhino3dm must be present."""

    def test_empty_objects_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            export_to_3dm([])


@_RHINO3DM_AVAILABLE
class TestNurbsCurveRoundTrip:
    """NURBS curve export → reimport: CP nets identical to 1e-9."""

    def _make_objects(self, cps, knots, degree, weights=None):
        payload = build_nurbs_curve_payload(degree, knots, cps, weights)
        return [{"kind": "sketch", "content_json": payload}]

    def test_open_cubic_non_rational(self):
        """Degree-3 open cubic, 4 control points."""
        cps = [
            [0.0, 0.0, 0.0],
            [1.0, 2.0, 0.0],
            [2.0, -1.0, 0.0],
            [3.0, 0.0, 0.0],
        ]
        # rhino3dm: n + degree - 1 = 4 + 3 - 1 = 6 knots
        knots = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
        data = export_to_3dm(self._make_objects(cps, knots, 3))
        objs = _read_3dm_objects(data)
        assert len(objs) >= 1, "Expected at least one object in .3dm"
        geom = objs[0][0]
        rt_cps = _extract_nurbs_curve_cps(geom)
        _assert_cps_equal(cps, rt_cps, label="open cubic non-rational")

    def test_open_linear(self):
        """Degree-1 line (2 control points)."""
        cps = [[1.5, 2.5, 3.5], [4.5, 5.5, 6.5]]
        knots = [0.0, 1.0]
        data = export_to_3dm(self._make_objects(cps, knots, 1))
        objs = _read_3dm_objects(data)
        assert len(objs) >= 1
        geom = objs[0][0]
        rt_cps = _extract_nurbs_curve_cps(geom)
        _assert_cps_equal(cps, rt_cps, label="linear")

    def test_rational_quarter_arc(self):
        """Rational degree-2 quarter circle arc (canonical weights 1, 1/sqrt(2), 1)."""
        w = math.sqrt(2) / 2  # 1/sqrt(2) ≈ 0.7071067811865476
        cps = [[1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]]
        knots = [0.0, 0.0, 1.0, 1.0]
        weights = [1.0, w, 1.0]
        data = export_to_3dm(self._make_objects(cps, knots, 2, weights))
        objs = _read_3dm_objects(data)
        assert len(objs) >= 1
        geom = objs[0][0]
        rt_cps = _extract_nurbs_curve_cps(geom)
        _assert_cps_equal(cps, rt_cps, _TOL, label="rational quarter-arc CPs")

    def test_open_quadratic_5pts(self):
        """Degree-2, 5 control points (knot vector length = 5+2-1 = 6)."""
        cps = [
            [0.0, 0.0, 0.0],
            [0.5, 1.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.5, 1.0, 0.0],
            [2.0, 0.0, 0.0],
        ]
        knots = [0.0, 0.0, 0.5, 1.0, 1.5, 2.0, 2.0]
        # 5 + 2 - 1 = 6 → but rhino3dm uses (n + degree - 1) = 6 as well
        # Ensure correct count: len(knots) == n + degree - 1 → 5+2-1=6
        knots = knots[:6]  # trim to 6
        data = export_to_3dm(self._make_objects(cps, knots, 2))
        objs = _read_3dm_objects(data)
        assert len(objs) >= 1
        geom = objs[0][0]
        rt_cps = _extract_nurbs_curve_cps(geom)
        _assert_cps_equal(cps, rt_cps, label="quadratic 5-point")

    def test_3d_cubic_helix_like(self):
        """Non-planar cubic with z variation."""
        cps = [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 1.0],
            [1.0, 1.0, 2.0],
            [0.0, 1.0, 3.0],
        ]
        knots = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
        data = export_to_3dm(self._make_objects(cps, knots, 3))
        objs = _read_3dm_objects(data)
        assert len(objs) >= 1
        geom = objs[0][0]
        rt_cps = _extract_nurbs_curve_cps(geom)
        _assert_cps_equal(cps, rt_cps, label="3D cubic")


@_RHINO3DM_AVAILABLE
class TestNurbsSurfaceRoundTrip:
    """NURBS surface export → reimport: CP nets identical to 1e-9."""

    def _make_objects(self, degree_u, degree_v, knots_u, knots_v, cps, weights=None):
        payload = build_nurbs_surface_payload(
            degree_u, degree_v, knots_u, knots_v, cps, weights
        )
        return [{"kind": "surf", "content_json": payload}]

    def test_bilinear_flat(self):
        """2x2 bilinear flat patch (degree 1x1)."""
        cps = [
            [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            [[1.0, 0.0, 0.0], [1.0, 1.0, 0.0]],
        ]
        data = export_to_3dm(self._make_objects(1, 1, [0.0, 1.0], [0.0, 1.0], cps))
        objs = _read_3dm_objects(data)
        assert len(objs) >= 1
        geom = objs[0][0]
        rt_cps = _extract_nurbs_surface_cps(geom)
        _assert_surface_cps_equal(cps, rt_cps, label="bilinear flat")

    def test_biquadratic_3x3(self):
        """3x3 biquadratic patch (degree 2x2)."""
        cps = [
            [[0.0, 0.0, 0.0], [0.0, 1.0, 0.5], [0.0, 2.0, 0.0]],
            [[1.0, 0.0, 0.5], [1.0, 1.0, 1.0], [1.0, 2.0, 0.5]],
            [[2.0, 0.0, 0.0], [2.0, 1.0, 0.5], [2.0, 2.0, 0.0]],
        ]
        knots_u = [0.0, 0.0, 1.0, 1.0]
        knots_v = [0.0, 0.0, 1.0, 1.0]
        data = export_to_3dm(
            self._make_objects(2, 2, knots_u, knots_v, cps)
        )
        objs = _read_3dm_objects(data)
        assert len(objs) >= 1
        geom = objs[0][0]
        rt_cps = _extract_nurbs_surface_cps(geom)
        _assert_surface_cps_equal(cps, rt_cps, label="biquadratic 3x3")

    def test_bicubic_4x4(self):
        """4x4 bicubic patch (degree 3x3)."""
        cps = [
            [[float(i), float(j), float(i * j) / 9.0] for j in range(4)]
            for i in range(4)
        ]
        knots_u = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
        knots_v = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
        data = export_to_3dm(
            self._make_objects(3, 3, knots_u, knots_v, cps)
        )
        objs = _read_3dm_objects(data)
        assert len(objs) >= 1
        geom = objs[0][0]
        rt_cps = _extract_nurbs_surface_cps(geom)
        _assert_surface_cps_equal(cps, rt_cps, label="bicubic 4x4")

    def test_rational_cylinder_sector(self):
        """Rational bilinear patch with non-unit weights (approximating a bent patch)."""
        cps = [
            [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            [[1.0, 0.0, 0.0], [1.0, 1.0, 0.0]],
        ]
        weights = [[1.0, 0.8], [0.8, 1.0]]
        data = export_to_3dm(
            self._make_objects(1, 1, [0.0, 1.0], [0.0, 1.0], cps, weights)
        )
        objs = _read_3dm_objects(data)
        assert len(objs) >= 1
        geom = objs[0][0]
        rt_cps = _extract_nurbs_surface_cps(geom)
        _assert_surface_cps_equal(cps, rt_cps, _TOL, label="rational bilinear CPs")

    def test_asymmetric_2x3_quadratic(self):
        """2x3 patch: degree_u=1, degree_v=2."""
        cps = [
            [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 2.0, 0.0]],
            [[1.0, 0.0, 0.0], [1.0, 1.0, 0.5], [1.0, 2.0, 0.0]],
        ]
        knots_u = [0.0, 1.0]          # n_u + degree_u - 1 = 2+1-1 = 2
        knots_v = [0.0, 0.0, 1.0, 1.0]  # n_v + degree_v - 1 = 3+2-1 = 4
        data = export_to_3dm(
            self._make_objects(1, 2, knots_u, knots_v, cps)
        )
        objs = _read_3dm_objects(data)
        assert len(objs) >= 1
        geom = objs[0][0]
        rt_cps = _extract_nurbs_surface_cps(geom)
        _assert_surface_cps_equal(cps, rt_cps, label="asymmetric 2x3")


@_RHINO3DM_AVAILABLE
class TestMixedObjectExport:
    """Mixed curve + surface + point → parseable .3dm."""

    def test_mixed_produces_valid_3dm(self):
        curve_payload = build_nurbs_curve_payload(
            1, [0.0, 1.0], [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
        )
        surface_payload = build_nurbs_surface_payload(
            1, 1, [0.0, 1.0], [0.0, 1.0],
            [[[0.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
             [[1.0, 0.0, 0.0], [1.0, 1.0, 0.0]]]
        )
        point_obj = {
            "kind": "point",
            "content_json": {"x": 5.0, "y": 5.0, "z": 5.0},
        }
        objects = [
            {"kind": "sketch", "content_json": curve_payload},
            {"kind": "surf", "content_json": surface_payload},
            point_obj,
        ]
        data = export_to_3dm(objects)
        assert len(data) > 0, "Expected non-empty .3dm bytes"
        # Should contain at least a .3dm magic header
        assert data[:4] == b"3dm\x00" or b"3dm" in data[:16], (
            "Output does not look like a .3dm file"
        )
        objs = _read_3dm_objects(data)
        assert len(objs) >= 2, f"Expected ≥ 2 objects, got {len(objs)}"


@_RHINO3DM_AVAILABLE
class TestImportErrorWhenNoRhino3dm:
    """Verify that export_to_3dm raises ImportError when rhino3dm is absent."""

    def test_raises_import_error(self, monkeypatch):
        """Simulate rhino3dm absence via sys.modules manipulation."""
        # Save original
        original = sys.modules.get("rhino3dm")
        # Block import
        sys.modules["rhino3dm"] = None  # type: ignore[assignment]

        # Force reimport of the module function to pick up blocked dep
        import kerf_imports.export_3dm as _mod
        import importlib as _il
        _il.reload(_mod)

        try:
            with pytest.raises((ImportError, TypeError)):
                _mod.export_to_3dm([{"kind": "sketch", "content_json": {}}])
        finally:
            # Restore
            if original is None:
                del sys.modules["rhino3dm"]
            else:
                sys.modules["rhino3dm"] = original
            _il.reload(_mod)
