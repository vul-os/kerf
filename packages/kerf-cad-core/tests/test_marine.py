"""
Tests for kerf_cad_core.marine — hull recipes, fairing metrics, hydrostatics,
and LLM tool wrappers.

All tests are pure-Python, hermetic: no OCC, no DB, no network, no disk fixtures.
Tests run deterministically with fixed numeric inputs.

Hydrostatics identity: for a box-barge (constant half-breadth = B/2 over all
stations and waterlines), displaced volume must equal L × B × T within tolerance
of Simpson's rule.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.marine.hull import (
    hull_from_offsets,
    fairing_report,
    hydrostatics,
    _simpsons_rule,
    _natural_cubic_spline_second_derivs,
    _spline_bending_energy,
    HullOffsetTable,
    HullControlNet,
)
from kerf_cad_core.marine.tools import (
    run_marine_hull_from_offsets,
    run_marine_fairing_report,
    run_marine_hydrostatics,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_ctx():
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    return ProjectCtx(
        pool=None, storage=None,
        project_id=uuid.uuid4(), user_id=uuid.uuid4(),
        role="owner", http_client=None,
    )


def _ok(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is True, f"Expected ok=True, got: {d}"
    return d


def _err(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is False, f"Expected ok=False, got: {d}"
    assert "errors" in d, f"Expected 'errors' key in: {d}"
    return d


def _box_barge_offsets(
    stations: list[float],
    waterlines: list[float],
    half_beam: float,
) -> list[dict]:
    """Generate a rectangular (box-barge) offset table with constant half-breadth."""
    rows = []
    for st in stations:
        for wl in waterlines:
            rows.append({"station": st, "waterline": wl, "half_breadth": half_beam})
    return rows


def _simple_offsets() -> list[dict]:
    """A small 3-station × 3-waterline hull for basic smoke tests."""
    return [
        {"station": 0.0, "waterline": 0.0, "half_breadth": 0.5},
        {"station": 0.0, "waterline": 1.0, "half_breadth": 1.0},
        {"station": 0.0, "waterline": 2.0, "half_breadth": 1.2},
        {"station": 5.0, "waterline": 0.0, "half_breadth": 1.0},
        {"station": 5.0, "waterline": 1.0, "half_breadth": 2.0},
        {"station": 5.0, "waterline": 2.0, "half_breadth": 2.5},
        {"station": 10.0, "waterline": 0.0, "half_breadth": 0.5},
        {"station": 10.0, "waterline": 1.0, "half_breadth": 1.0},
        {"station": 10.0, "waterline": 2.0, "half_breadth": 1.2},
    ]


# ===========================================================================
# 1. Simpson's rule tests
# ===========================================================================

class TestSimpsonsRule:

    def test_constant_function(self):
        """∫₀^L c dx = c × L, exact for any polynomial."""
        x = [0.0, 1.0, 2.0, 3.0, 4.0]
        y = [3.0] * 5
        result = _simpsons_rule(x, y)
        assert abs(result - 12.0) < 1e-10

    def test_linear_function(self):
        """∫₀^4 x dx = 8.0; Simpson is exact for linear."""
        x = [0.0, 1.0, 2.0, 3.0, 4.0]
        y = [xi for xi in x]
        result = _simpsons_rule(x, y)
        assert abs(result - 8.0) < 1e-10

    def test_quadratic_function(self):
        """∫₀^2 x² dx = 8/3; Simpson exact for quadratics (odd n)."""
        x = [0.0, 0.5, 1.0, 1.5, 2.0]
        y = [xi ** 2 for xi in x]
        result = _simpsons_rule(x, y)
        assert abs(result - 8.0 / 3.0) < 1e-10

    def test_cubic_function(self):
        """∫₀^2 x³ dx = 4.0; Simpson exact for cubics (odd n)."""
        x = [0.0, 0.5, 1.0, 1.5, 2.0]
        y = [xi ** 3 for xi in x]
        result = _simpsons_rule(x, y)
        assert abs(result - 4.0) < 1e-10

    def test_single_interval_trapezoid(self):
        """Two points → trapezoid rule."""
        x = [0.0, 2.0]
        y = [1.0, 3.0]
        assert abs(_simpsons_rule(x, y) - 4.0) < 1e-12

    def test_empty_returns_zero(self):
        assert _simpsons_rule([], []) == 0.0

    def test_single_point_returns_zero(self):
        assert _simpsons_rule([1.0], [5.0]) == 0.0

    def test_uneven_spacing(self):
        """∫₀^3 1 dx = 3 with uneven spacing."""
        x = [0.0, 0.5, 3.0]
        y = [1.0, 1.0, 1.0]
        result = _simpsons_rule(x, y)
        assert abs(result - 3.0) < 1e-10


# ===========================================================================
# 2. hull_from_offsets — basic construction
# ===========================================================================

class TestHullFromOffsets:

    def test_simple_hull_ok(self):
        result = hull_from_offsets(_simple_offsets())
        assert result["ok"] is True
        assert result["op"] == "marine_loft_hull"

    def test_dimensions(self):
        result = hull_from_offsets(_simple_offsets())
        assert result["loa"] == pytest.approx(10.0)
        assert result["depth"] == pytest.approx(2.0)
        assert result["max_half_beam"] == pytest.approx(2.5)
        assert result["station_count"] == 3
        assert result["waterline_count"] == 3

    def test_sections_sorted_by_waterline(self):
        """Sections must list points in ascending waterline order."""
        result = hull_from_offsets(_simple_offsets())
        for section in result["sections"]:
            wls = [p["wl"] for p in section["points"]]
            assert wls == sorted(wls)

    def test_knot_params_present(self):
        result = hull_from_offsets(_simple_offsets())
        kp = result["knot_params"]
        assert "station_params" in kp
        assert "waterline_params" in kp
        assert kp["degree_u"] >= 1
        assert kp["degree_v"] >= 1

    def test_knot_params_normalised(self):
        """station_params must start at 0 and end at 1."""
        result = hull_from_offsets(_simple_offsets())
        sp = result["knot_params"]["station_params"]
        assert sp[0] == pytest.approx(0.0)
        assert sp[-1] == pytest.approx(1.0)

    def test_degree_capped_at_3(self):
        """Degree should not exceed 3 regardless of data count."""
        offsets = _box_barge_offsets(
            stations=[0, 2, 4, 6, 8, 10],
            waterlines=[0, 1, 2, 3],
            half_beam=1.0,
        )
        result = hull_from_offsets(offsets)
        assert result["knot_params"]["degree_u"] == 3
        assert result["knot_params"]["degree_v"] == 3

    def test_two_station_minimum(self):
        """Only 2 stations and 2 waterlines — should still succeed."""
        offsets = [
            {"station": 0.0, "waterline": 0.0, "half_breadth": 1.0},
            {"station": 0.0, "waterline": 1.0, "half_breadth": 1.5},
            {"station": 5.0, "waterline": 0.0, "half_breadth": 1.0},
            {"station": 5.0, "waterline": 1.0, "half_breadth": 1.5},
        ]
        result = hull_from_offsets(offsets)
        assert result["ok"] is True

    def test_missing_wl_at_station_skipped(self):
        """Sparse table: not all stations cover all waterlines."""
        offsets = _simple_offsets()
        # Remove one entry
        offsets = [r for r in offsets if not (r["station"] == 5.0 and r["waterline"] == 2.0)]
        result = hull_from_offsets(offsets)
        assert result["ok"] is True
        # Station 5.0 should have 2 points instead of 3
        for sec in result["sections"]:
            if sec["station"] == 5.0:
                assert len(sec["points"]) == 2


# ===========================================================================
# 3. hull_from_offsets — validation / error paths
# ===========================================================================

class TestHullFromOffsetsErrors:

    def test_not_a_list(self):
        result = hull_from_offsets("bad input")
        assert result["ok"] is False
        assert result["errors"]

    def test_too_few_rows(self):
        result = hull_from_offsets([
            {"station": 0.0, "waterline": 0.0, "half_breadth": 1.0},
            {"station": 1.0, "waterline": 0.0, "half_breadth": 1.0},
        ])
        assert result["ok"] is False
        assert any("at least 3" in e for e in result["errors"])

    def test_missing_field(self):
        result = hull_from_offsets([
            {"station": 0.0, "waterline": 0.0},           # missing half_breadth
            {"station": 1.0, "waterline": 0.0, "half_breadth": 1.0},
            {"station": 2.0, "waterline": 0.0, "half_breadth": 1.0},
        ])
        assert result["ok"] is False
        assert any("half_breadth" in e for e in result["errors"])

    def test_negative_half_breadth(self):
        result = hull_from_offsets([
            {"station": 0.0, "waterline": 0.0, "half_breadth": -1.0},
            {"station": 1.0, "waterline": 0.0, "half_breadth": 1.0},
            {"station": 2.0, "waterline": 0.0, "half_breadth": 1.0},
        ])
        assert result["ok"] is False
        assert any(">= 0" in e for e in result["errors"])

    def test_duplicate_station_waterline(self):
        result = hull_from_offsets([
            {"station": 0.0, "waterline": 0.0, "half_breadth": 1.0},
            {"station": 0.0, "waterline": 0.0, "half_breadth": 2.0},  # duplicate
            {"station": 1.0, "waterline": 0.0, "half_breadth": 1.0},
            {"station": 1.0, "waterline": 1.0, "half_breadth": 1.0},
            {"station": 0.0, "waterline": 1.0, "half_breadth": 1.0},
        ])
        assert result["ok"] is False
        assert any("duplicate" in e for e in result["errors"])

    def test_single_station_error(self):
        """All rows on same station → only 1 station → error."""
        result = hull_from_offsets([
            {"station": 5.0, "waterline": 0.0, "half_breadth": 1.0},
            {"station": 5.0, "waterline": 1.0, "half_breadth": 1.5},
            {"station": 5.0, "waterline": 2.0, "half_breadth": 1.8},
        ])
        assert result["ok"] is False
        assert any("station" in e for e in result["errors"])

    def test_single_waterline_error(self):
        """All rows on same waterline → only 1 waterline → error."""
        result = hull_from_offsets([
            {"station": 0.0, "waterline": 0.0, "half_breadth": 1.0},
            {"station": 5.0, "waterline": 0.0, "half_breadth": 2.0},
            {"station": 10.0, "waterline": 0.0, "half_breadth": 1.0},
        ])
        assert result["ok"] is False
        assert any("waterline" in e for e in result["errors"])

    def test_non_numeric_field(self):
        result = hull_from_offsets([
            {"station": "bow", "waterline": 0.0, "half_breadth": 1.0},
            {"station": 5.0,   "waterline": 0.0, "half_breadth": 1.0},
            {"station": 10.0,  "waterline": 0.0, "half_breadth": 1.0},
        ])
        assert result["ok"] is False

    def test_empty_list(self):
        result = hull_from_offsets([])
        assert result["ok"] is False


# ===========================================================================
# 4. Hydrostatics — box-barge identity
# ===========================================================================

class TestHydrostatics:

    def _box_result(self, L, B, T, n_st=5, n_wl=5):
        """Build a box-barge and return hydrostatics result."""
        stations = [L * i / (n_st - 1) for i in range(n_st)]
        waterlines = [T * i / (n_wl - 1) for i in range(n_wl)]
        offsets = _box_barge_offsets(stations, waterlines, B / 2.0)
        return hydrostatics(offsets)

    def test_box_barge_volume_identity(self):
        """∇ = L × B × T for a box barge (within Simpson tolerance)."""
        L, B, T = 20.0, 4.0, 2.0
        result = self._box_result(L, B, T)
        assert result["ok"] is True
        expected = L * B * T
        assert abs(result["displaced_volume_m3"] - expected) < 0.1

    def test_box_barge_volume_identity_larger(self):
        """Box barge with more stations for better Simpson accuracy."""
        L, B, T = 100.0, 12.0, 5.0
        result = self._box_result(L, B, T, n_st=9, n_wl=5)
        assert result["ok"] is True
        expected = L * B * T
        assert abs(result["displaced_volume_m3"] - expected) < 1.0

    def test_box_barge_waterplane_area(self):
        """Awp = L × B for a box barge."""
        L, B, T = 20.0, 4.0, 2.0
        result = self._box_result(L, B, T)
        expected = L * B
        assert abs(result["waterplane_area_m2"] - expected) < 0.1

    def test_box_barge_lcb_at_midship(self):
        """LCB of a symmetric box barge is at L/2 from bow."""
        L, B, T = 20.0, 4.0, 2.0
        result = self._box_result(L, B, T)
        assert abs(result["lcb_from_bow_m"] - L / 2.0) < 0.5

    def test_design_waterline_partial_immersion(self):
        """Partial immersion (design_wl < max_wl) reduces volume."""
        L, B, T = 20.0, 4.0, 2.0
        full = self._box_result(L, B, T)
        # Build with design waterline at T/2
        stations = [L * i / 4 for i in range(5)]
        waterlines = [T * i / 4 for i in range(5)]
        offsets = _box_barge_offsets(stations, waterlines, B / 2.0)
        partial = hydrostatics(offsets, design_waterline=T / 2.0)
        assert partial["ok"] is True
        assert partial["displaced_volume_m3"] < full["displaced_volume_m3"] - 0.01

    def test_design_waterline_at_max_equals_default(self):
        """design_waterline=T should give same result as default."""
        L, B, T = 20.0, 4.0, 2.0
        stations = [L * i / 4 for i in range(5)]
        waterlines = [T * i / 4 for i in range(5)]
        offsets = _box_barge_offsets(stations, waterlines, B / 2.0)
        r1 = hydrostatics(offsets)
        r2 = hydrostatics(offsets, design_waterline=T)
        assert abs(r1["displaced_volume_m3"] - r2["displaced_volume_m3"]) < 1e-6

    def test_design_waterline_below_keel_error(self):
        """design_waterline below keel → friendly error."""
        offsets = _simple_offsets()
        result = hydrostatics(offsets, design_waterline=-5.0)
        assert result["ok"] is False
        assert result["errors"]

    def test_invalid_design_waterline_type(self):
        offsets = _simple_offsets()
        result = hydrostatics(offsets, design_waterline="high")
        assert result["ok"] is False
        assert result["errors"]

    def test_hydrostatics_on_simple_hull(self):
        """Hydrostatics runs without error on the simple test hull."""
        result = hydrostatics(_simple_offsets())
        assert result["ok"] is True
        assert result["displaced_volume_m3"] > 0
        assert result["waterplane_area_m2"] > 0
        assert result["lcb_from_bow_m"] >= 0

    def test_bad_offsets_propagated(self):
        result = hydrostatics("not a list")
        assert result["ok"] is False


# ===========================================================================
# 5. Fairing report
# ===========================================================================

class TestFairingReport:

    def test_smooth_hull_no_kinks(self):
        """A monotone-increasing hull should have no kinks."""
        # Station 5.0 is symmetric and monotone-increasing
        offsets = _simple_offsets()
        result = fairing_report(offsets)
        assert result["ok"] is True
        for entry in result["curvature_monotonicity"]:
            assert not entry["kink_detected"], (
                f"Unexpected kink at station {entry['station']}"
            )

    def test_kink_detected_on_injected_kink(self):
        """Inject a non-monotone dip into a station's profile → kink flagged."""
        offsets = [
            # Station 0: monotone
            {"station": 0.0, "waterline": 0.0, "half_breadth": 1.0},
            {"station": 0.0, "waterline": 1.0, "half_breadth": 2.0},
            {"station": 0.0, "waterline": 2.0, "half_breadth": 3.0},
            {"station": 0.0, "waterline": 3.0, "half_breadth": 4.0},
            # Station 5: kink — dip then rise then fall (two extra sign changes)
            {"station": 5.0, "waterline": 0.0, "half_breadth": 1.0},
            {"station": 5.0, "waterline": 1.0, "half_breadth": 3.0},
            {"station": 5.0, "waterline": 2.0, "half_breadth": 1.0},  # dip (kink)
            {"station": 5.0, "waterline": 3.0, "half_breadth": 4.0},  # rise
            {"station": 5.0, "waterline": 4.0, "half_breadth": 2.0},  # fall
            # Station 10: monotone
            {"station": 10.0, "waterline": 0.0, "half_breadth": 0.5},
            {"station": 10.0, "waterline": 1.0, "half_breadth": 1.5},
            {"station": 10.0, "waterline": 2.0, "half_breadth": 2.5},
            {"station": 10.0, "waterline": 3.0, "half_breadth": 3.5},
            {"station": 10.0, "waterline": 4.0, "half_breadth": 3.0},
        ]
        result = fairing_report(offsets)
        assert result["ok"] is True
        kink_stations = [
            e["station"]
            for e in result["curvature_monotonicity"]
            if e["kink_detected"]
        ]
        assert 5.0 in kink_stations, (
            f"Expected station 5.0 to have a kink; got kinks at {kink_stations}"
        )

    def test_monotone_hull_passes(self):
        """A strictly monotone-increasing box barge has no kinks."""
        offsets = _box_barge_offsets(
            stations=[0.0, 5.0, 10.0],
            waterlines=[0.0, 1.0, 2.0],
            half_beam=2.0,
        )
        result = fairing_report(offsets)
        assert result["ok"] is True
        for entry in result["curvature_monotonicity"]:
            assert not entry["kink_detected"]

    def test_batten_energy_positive(self):
        """Bending energy must be >= 0 for any valid input."""
        result = fairing_report(_simple_offsets())
        assert result["ok"] is True
        for entry in result["batten_energy"]:
            assert entry["energy"] >= 0.0

    def test_batten_energy_zero_for_collinear(self):
        """Linear Y vs WL profile → energy should be ~0 (no bending)."""
        offsets = [
            {"station": 0.0, "waterline": 0.0, "half_breadth": 0.0},
            {"station": 0.0, "waterline": 1.0, "half_breadth": 1.0},
            {"station": 0.0, "waterline": 2.0, "half_breadth": 2.0},
            {"station": 5.0, "waterline": 0.0, "half_breadth": 0.0},
            {"station": 5.0, "waterline": 1.0, "half_breadth": 1.0},
            {"station": 5.0, "waterline": 2.0, "half_breadth": 2.0},
        ]
        result = fairing_report(offsets)
        assert result["ok"] is True
        for entry in result["batten_energy"]:
            assert entry["energy"] == pytest.approx(0.0, abs=1e-9)

    def test_roughness_zero_for_constant_hull(self):
        """Box barge (constant offsets) → roughness = 0."""
        offsets = _box_barge_offsets(
            stations=[0.0, 5.0, 10.0],
            waterlines=[0.0, 1.0, 2.0],
            half_beam=2.0,
        )
        result = fairing_report(offsets)
        assert result["ok"] is True
        assert result["overall_roughness"] == pytest.approx(0.0, abs=1e-8)
        for r in result["roughness_per_waterline"]:
            assert r["rms_second_diff"] == pytest.approx(0.0, abs=1e-8)

    def test_roughness_nonzero_for_irregular_hull(self):
        """A hull with irregular stations should have nonzero roughness."""
        offsets = [
            {"station": 0.0,  "waterline": 0.0, "half_breadth": 1.0},
            {"station": 0.0,  "waterline": 1.0, "half_breadth": 2.0},
            {"station": 5.0,  "waterline": 0.0, "half_breadth": 3.0},   # big jump
            {"station": 5.0,  "waterline": 1.0, "half_breadth": 1.0},   # big drop
            {"station": 10.0, "waterline": 0.0, "half_breadth": 1.0},
            {"station": 10.0, "waterline": 1.0, "half_breadth": 2.0},
        ]
        result = fairing_report(offsets)
        assert result["ok"] is True
        assert result["overall_roughness"] > 0.0

    def test_fairing_report_bad_input(self):
        result = fairing_report({"bad": "input"})
        assert result["ok"] is False

    def test_fairing_report_missing_field(self):
        result = fairing_report([
            {"station": 0.0, "waterline": 0.0},  # missing half_breadth
            {"station": 1.0, "waterline": 0.0, "half_breadth": 1.0},
            {"station": 2.0, "waterline": 1.0, "half_breadth": 1.0},
        ])
        assert result["ok"] is False


# ===========================================================================
# 6. Spline helpers
# ===========================================================================

class TestSplineHelpers:

    def test_second_derivs_linear(self):
        """Natural spline through a linear function → all M = 0."""
        x = [0.0, 1.0, 2.0, 3.0]
        y = [0.0, 1.0, 2.0, 3.0]
        M = _natural_cubic_spline_second_derivs(x, y)
        for mi in M:
            assert abs(mi) < 1e-10

    def test_second_derivs_length(self):
        x = [0.0, 1.0, 2.0, 3.0, 4.0]
        y = [0.0, 1.0, 4.0, 9.0, 16.0]
        M = _natural_cubic_spline_second_derivs(x, y)
        assert len(M) == 5

    def test_bending_energy_nonnegative(self):
        x = [0.0, 1.0, 2.0, 3.0]
        y = [0.5, 2.0, 1.5, 3.0]
        e = _spline_bending_energy(x, y)
        assert e >= 0.0

    def test_bending_energy_zero_for_linear(self):
        x = [0.0, 1.0, 2.0, 3.0]
        y = [0.0, 1.0, 2.0, 3.0]
        e = _spline_bending_energy(x, y)
        assert abs(e) < 1e-10


# ===========================================================================
# 7. LLM tool wrappers
# ===========================================================================

class TestMarineTools:

    def _ctx(self):
        return _make_ctx()

    def test_hull_tool_ok(self):
        ctx = self._ctx()
        payload = json.dumps({"offsets": _simple_offsets()})
        raw = _run(run_marine_hull_from_offsets(ctx, payload.encode()))
        d = _ok(raw)
        assert d["op"] == "marine_loft_hull"

    def test_hull_tool_bad_json(self):
        ctx = self._ctx()
        raw = _run(run_marine_hull_from_offsets(ctx, b"not json"))
        d = json.loads(raw)
        assert "error" in d or d.get("ok") is False

    def test_hull_tool_missing_offsets_key(self):
        ctx = self._ctx()
        payload = json.dumps({"data": []})
        raw = _run(run_marine_hull_from_offsets(ctx, payload.encode()))
        _err(raw)

    def test_hull_tool_invalid_offsets(self):
        ctx = self._ctx()
        payload = json.dumps({"offsets": "oops"})
        raw = _run(run_marine_hull_from_offsets(ctx, payload.encode()))
        _err(raw)

    def test_fairing_tool_ok(self):
        ctx = self._ctx()
        payload = json.dumps({"offsets": _simple_offsets()})
        raw = _run(run_marine_fairing_report(ctx, payload.encode()))
        d = _ok(raw)
        assert "curvature_monotonicity" in d
        assert "batten_energy" in d
        assert "roughness_per_waterline" in d

    def test_fairing_tool_bad_json(self):
        ctx = self._ctx()
        raw = _run(run_marine_fairing_report(ctx, b"bad"))
        d = json.loads(raw)
        assert "error" in d or d.get("ok") is False

    def test_fairing_tool_missing_offsets_key(self):
        ctx = self._ctx()
        payload = json.dumps({})
        raw = _run(run_marine_fairing_report(ctx, payload.encode()))
        _err(raw)

    def test_hydro_tool_ok(self):
        ctx = self._ctx()
        payload = json.dumps({"offsets": _simple_offsets()})
        raw = _run(run_marine_hydrostatics(ctx, payload.encode()))
        d = _ok(raw)
        assert "waterplane_area_m2" in d
        assert "displaced_volume_m3" in d
        assert "lcb_from_bow_m" in d

    def test_hydro_tool_with_design_wl(self):
        ctx = self._ctx()
        payload = json.dumps({"offsets": _simple_offsets(), "design_waterline": 1.5})
        raw = _run(run_marine_hydrostatics(ctx, payload.encode()))
        _ok(raw)

    def test_hydro_tool_bad_json(self):
        ctx = self._ctx()
        raw = _run(run_marine_hydrostatics(ctx, b"{bad}"))
        d = json.loads(raw)
        assert "error" in d or d.get("ok") is False

    def test_hydro_tool_missing_offsets(self):
        ctx = self._ctx()
        payload = json.dumps({"design_waterline": 1.0})
        raw = _run(run_marine_hydrostatics(ctx, payload.encode()))
        _err(raw)

    def test_hydro_tool_invalid_design_wl(self):
        ctx = self._ctx()
        payload = json.dumps({"offsets": _simple_offsets(), "design_waterline": "deep"})
        raw = _run(run_marine_hydrostatics(ctx, payload.encode()))
        _err(raw)

    def test_hydro_tool_below_keel(self):
        ctx = self._ctx()
        payload = json.dumps({"offsets": _simple_offsets(), "design_waterline": -10.0})
        raw = _run(run_marine_hydrostatics(ctx, payload.encode()))
        _err(raw)


# ===========================================================================
# 8. Edge cases and additional coverage
# ===========================================================================

class TestEdgeCases:

    def test_hull_with_zero_half_breadth_at_keel(self):
        """Keel half-breadth = 0 (sharp keel) is valid."""
        offsets = [
            {"station": 0.0, "waterline": 0.0, "half_breadth": 0.0},
            {"station": 0.0, "waterline": 1.0, "half_breadth": 1.0},
            {"station": 0.0, "waterline": 2.0, "half_breadth": 1.5},
            {"station": 10.0, "waterline": 0.0, "half_breadth": 0.0},
            {"station": 10.0, "waterline": 1.0, "half_breadth": 1.0},
            {"station": 10.0, "waterline": 2.0, "half_breadth": 1.5},
        ]
        result = hull_from_offsets(offsets)
        assert result["ok"] is True

    def test_hydrostatics_with_zero_keel_breadths(self):
        """Sharp keel (half_breadth=0 at WL=0) should not error."""
        offsets = [
            {"station": 0.0,  "waterline": 0.0, "half_breadth": 0.0},
            {"station": 0.0,  "waterline": 2.0, "half_breadth": 2.0},
            {"station": 5.0,  "waterline": 0.0, "half_breadth": 0.0},
            {"station": 5.0,  "waterline": 2.0, "half_breadth": 2.0},
            {"station": 10.0, "waterline": 0.0, "half_breadth": 0.0},
            {"station": 10.0, "waterline": 2.0, "half_breadth": 2.0},
        ]
        result = hydrostatics(offsets)
        assert result["ok"] is True
        assert result["displaced_volume_m3"] > 0

    def test_fairing_report_single_waterline_at_station(self):
        """Station with only 1 point should not crash fairing report."""
        offsets = [
            # Station 0 has 1 WL, station 5 and 10 have 2 WLs
            {"station": 0.0,  "waterline": 0.0, "half_breadth": 1.0},
            {"station": 5.0,  "waterline": 0.0, "half_breadth": 1.0},
            {"station": 5.0,  "waterline": 1.0, "half_breadth": 2.0},
            {"station": 10.0, "waterline": 0.0, "half_breadth": 1.0},
            {"station": 10.0, "waterline": 1.0, "half_breadth": 2.0},
        ]
        result = fairing_report(offsets)
        assert result["ok"] is True

    def test_hull_sections_cover_all_stations(self):
        result = hull_from_offsets(_simple_offsets())
        assert result["ok"] is True
        section_stations = {sec["station"] for sec in result["sections"]}
        assert section_stations == {0.0, 5.0, 10.0}

    def test_box_barge_volume_5stations(self):
        """Another box-barge identity with 5 stations."""
        L, B, T = 50.0, 8.0, 3.0
        stations = [0.0, 12.5, 25.0, 37.5, 50.0]
        waterlines = [0.0, 1.0, 2.0, 3.0]
        offsets = _box_barge_offsets(stations, waterlines, B / 2.0)
        result = hydrostatics(offsets)
        assert result["ok"] is True
        assert abs(result["displaced_volume_m3"] - L * B * T) < 1.0

    def test_non_dict_row_in_offsets(self):
        """A row that is a list instead of dict should return friendly error."""
        result = hull_from_offsets([
            [0.0, 0.0, 1.0],   # wrong type
            {"station": 1.0, "waterline": 0.0, "half_breadth": 1.0},
            {"station": 2.0, "waterline": 1.0, "half_breadth": 1.0},
        ])
        assert result["ok"] is False

    def test_fairing_report_returns_all_stations(self):
        """curvature_monotonicity must have one entry per unique station."""
        offsets = _simple_offsets()
        result = fairing_report(offsets)
        assert result["ok"] is True
        stations_in_report = {e["station"] for e in result["curvature_monotonicity"]}
        assert stations_in_report == {0.0, 5.0, 10.0}

    def test_hydrostatics_returns_station_and_wl_counts(self):
        result = hydrostatics(_simple_offsets())
        assert result["ok"] is True
        assert result["station_count"] == 3
        assert result["waterline_count"] == 3
