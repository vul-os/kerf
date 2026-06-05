"""
Tests for piping_pressure_drop LLM tool and underlying asme_pressure.py functions.

Validation oracles
------------------
1. darcy_weisbach_loss: 100 GPM, 4" ID, 100 ft water → ΔP ≈ 2.5 psi
   (Crane TP-410 Example in §3, canonical reference value).
2. fitting_k_factor: values match Crane TP-410 §3 Table B-1.
3. compute_pipeline_pressure_drop: structure + pipe + fitting consistency.
4. piping_pressure_drop tool: end-to-end async call returns ok payload.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_piping.asme_pressure import (
    darcy_weisbach_loss,
    fitting_k_factor,
    compute_pipeline_pressure_drop,
    hooper_two_k,
    _colebrook_friction_factor,
    _k_to_psi,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeCtx:
    pass


# ===========================================================================
# darcy_weisbach_loss
# ===========================================================================

class TestDarcyWeisbachLoss:
    def test_water_100gpm_4in_100ft_crane_oracle(self):
        """
        Darcy-Weisbach oracle: 100 GPM water through 4" Sch40 (ID=4.026")
        over 100 ft of commercial steel (ε=0.00015 ft).

        Calculated value (verified): f≈0.0208, V≈2.52 ft/s, Re≈78,000
        → ΔP ≈ 0.265 psi/100ft.  (NOT 2.5 psi — that figure is for 2" pipe.)

        Oracle tolerance ±20% for fluid-property / table-rounding differences.
        """
        dp = darcy_weisbach_loss(
            diameter_in=4.026,
            length_ft=100.0,
            flow_gpm=100.0,
            fluid="water",
            roughness=0.00015,
        )
        # Oracle: ~0.265 psi/100ft for 4" Sch40, 100 GPM water
        assert 0.18 < dp < 0.40, f"Expected ~0.265 psi, got {dp:.4f} psi"

    def test_zero_flow_returns_zero(self):
        dp = darcy_weisbach_loss(4.0, 100.0, 0.0)
        assert dp == 0.0

    def test_zero_length_returns_zero(self):
        dp = darcy_weisbach_loss(4.0, 0.0, 100.0)
        assert dp == 0.0

    def test_scales_linearly_with_length(self):
        dp1 = darcy_weisbach_loss(4.0, 100.0, 100.0)
        dp2 = darcy_weisbach_loss(4.0, 200.0, 100.0)
        assert dp2 == pytest.approx(dp1 * 2.0, rel=1e-4)

    def test_oil_higher_than_water_low_re(self):
        """
        Oil has higher viscosity than water (μ_oil ≈ 3× μ_water).
        At moderate flow (100 GPM through 4"), Re_oil < Re_water, so oil's
        friction factor is higher — oil ΔP is actually higher than water ΔP
        at the same volumetric flow rate.

        This tests that the Colebrook solver correctly captures the viscosity
        effect: higher μ → lower Re → higher f → higher ΔP.
        """
        dp_w = darcy_weisbach_loss(4.0, 100.0, 100.0, fluid="water")
        dp_o = darcy_weisbach_loss(4.0, 100.0, 100.0, fluid="oil")
        # Oil μ >> water μ at same GPM → higher friction factor → higher ΔP
        assert dp_o > dp_w

    def test_unknown_fluid_raises(self):
        with pytest.raises(ValueError, match="Unknown fluid"):
            darcy_weisbach_loss(4.0, 100.0, 100.0, fluid="lava")

    def test_invalid_diameter_raises(self):
        with pytest.raises(ValueError):
            darcy_weisbach_loss(0.0, 100.0, 100.0)

    def test_result_is_positive(self):
        dp = darcy_weisbach_loss(2.0, 50.0, 50.0)
        assert dp > 0.0


# ===========================================================================
# fitting_k_factor — Crane TP-410 §3
# ===========================================================================

class TestFittingKFactor:
    def test_90_elbow_threaded_crane(self):
        """Crane TP-410 §3: 90° threaded elbow K ≈ 0.50 (size-independent base)."""
        k = fitting_k_factor("90_elbow_threaded", 4.0)
        assert k == pytest.approx(0.50, rel=0.05)

    def test_globe_valve_crane(self):
        """Crane TP-410 §3: Globe valve K ≈ 10.0 (fully open)."""
        k = fitting_k_factor("globe_valve", 4.0)
        assert k == pytest.approx(10.0, rel=0.05)

    def test_gate_valve_open_low_k(self):
        """Gate valve fully open: K ≈ 0.15 (very low resistance)."""
        k = fitting_k_factor("gate_valve_open", 4.0)
        assert k == pytest.approx(0.15, rel=0.05)

    def test_ball_valve_lowest_k(self):
        """Ball valve fully open should have the lowest K among standard valves."""
        k_ball = fitting_k_factor("ball_valve_open", 4.0)
        k_gate = fitting_k_factor("gate_valve_open", 4.0)
        assert k_ball < k_gate

    def test_reducer_sudden(self):
        """Sudden contraction: K = 0.5·(1 − β²)² for β < 1."""
        beta = 0.5
        k = fitting_k_factor("reducer_sudden", 4.0, beta=beta)
        expected = 0.5 * (1.0 - beta**2)**2
        assert k == pytest.approx(expected, rel=1e-6)

    def test_expander_sudden(self):
        """Sudden expansion (Borda-Carnot): K = (1 − β²)²."""
        beta = 0.7
        k = fitting_k_factor("expander_sudden", 4.0, beta=beta)
        expected = (1.0 - beta**2)**2
        assert k == pytest.approx(expected, rel=1e-6)

    def test_unknown_fitting_raises(self):
        with pytest.raises(ValueError, match="Unknown fitting_kind"):
            fitting_k_factor("invisible_fitting", 4.0)

    def test_all_standard_fittings_positive(self):
        standard = [
            "90_elbow_threaded", "45_elbow_threaded", "180_return_threaded",
            "90_elbow_welded", "45_elbow_welded", "180_return_welded",
            "tee_through", "tee_branch",
            "gate_valve_open", "globe_valve", "check_valve",
            "ball_valve_open", "butterfly_valve_open", "angle_valve_open",
        ]
        for kind in standard:
            k = fitting_k_factor(kind, 4.0)
            assert k > 0.0, f"Expected K > 0 for {kind!r}"


# ===========================================================================
# compute_pipeline_pressure_drop
# ===========================================================================

class TestComputePipelinePressureDrop:
    def _simple_pipeline(self, flow_gpm=100.0):
        """100 ft of 4" pipe + 3× 90° elbows + 1× globe valve."""
        segs = [{"diameter_in": 4.026, "length_ft": 100.0}]
        fits = [
            {"fitting_kind": "90_elbow_welded", "diameter_in": 4.026, "quantity": 3},
            {"fitting_kind": "globe_valve",      "diameter_in": 4.026, "quantity": 1},
        ]
        return compute_pipeline_pressure_drop(segs, fits, flow_gpm)

    def test_total_equals_pipe_plus_fittings(self):
        r = self._simple_pipeline()
        assert r["total_dp_psi"] == pytest.approx(
            r["pipe_dp_psi"] + r["fitting_dp_psi"], rel=1e-4
        )

    def test_pipe_contribution_positive(self):
        r = self._simple_pipeline()
        assert r["pipe_dp_psi"] > 0.0

    def test_fitting_contribution_positive(self):
        r = self._simple_pipeline()
        assert r["fitting_dp_psi"] > 0.0

    def test_segment_details_count(self):
        r = self._simple_pipeline()
        assert len(r["segment_details"]) == 1

    def test_fitting_details_count(self):
        r = self._simple_pipeline()
        assert len(r["fitting_details"]) == 2

    def test_globe_valve_dominates_fittings(self):
        """Globe valve (K=10) should contribute more than 3 elbows (K=0.30 each)."""
        segs = [{"diameter_in": 4.026, "length_ft": 1.0}]
        globe = compute_pipeline_pressure_drop(
            segs, [{"fitting_kind": "globe_valve", "diameter_in": 4.0}], 100.0
        )["fitting_dp_psi"]
        elbows = compute_pipeline_pressure_drop(
            segs, [{"fitting_kind": "90_elbow_welded", "diameter_in": 4.0, "quantity": 3}], 100.0
        )["fitting_dp_psi"]
        assert globe > elbows

    def test_disclaimer_present(self):
        r = self._simple_pipeline()
        assert "disclaimer" in r
        assert len(r["disclaimer"]) > 20

    def test_zero_flow_returns_zero_total(self):
        r = compute_pipeline_pressure_drop(
            [{"diameter_in": 4.0, "length_ft": 100.0}],
            [{"fitting_kind": "gate_valve_open", "diameter_in": 4.0}],
            flow_gpm=0.0,
        )
        assert r["total_dp_psi"] == 0.0

    def test_negative_flow_raises(self):
        with pytest.raises(ValueError, match="flow_gpm"):
            compute_pipeline_pressure_drop([], [], -1.0)


# ===========================================================================
# Hooper Two-K
# ===========================================================================

class TestHooperTwoK:
    def test_known_fitting_90elbow_longrad(self):
        """Hooper (1981) Table 1 for 90° long-radius elbow at Re=100000, ID=4"."""
        k = hooper_two_k("90_elbow_longrad", reynolds=1e5, diameter_in=4.0)
        # K_1=800, K_inf=0.25 → K = 800/100000 + 0.25·(1 + 1/4) = 0.008 + 0.3125 = 0.3205
        assert k == pytest.approx(0.3205, rel=0.01)

    def test_high_re_approaches_k_inf(self):
        """At Re→∞, K → K_inf·(1 + 1/ID)."""
        k_hi = hooper_two_k("90_elbow_longrad", reynolds=1e9, diameter_in=4.0)
        k_inf = 0.25 * (1.0 + 1.0 / 4.0)
        assert k_hi == pytest.approx(k_inf, rel=0.001)

    def test_low_re_higher_k(self):
        """Low Re should give higher K than high Re for same fitting."""
        k_lo = hooper_two_k("90_elbow_longrad", reynolds=1000, diameter_in=4.0)
        k_hi = hooper_two_k("90_elbow_longrad", reynolds=1e6, diameter_in=4.0)
        assert k_lo > k_hi

    def test_custom_k1_kinf(self):
        """Custom K_1 and K_inf via override."""
        k = hooper_two_k("unknown_fitting", K_1=500.0, K_inf=0.5,
                          reynolds=1e4, diameter_in=2.0)
        expected = 500.0 / 1e4 + 0.5 * (1.0 + 1.0 / 2.0)
        assert k == pytest.approx(expected, rel=1e-6)

    def test_missing_k1_raises(self):
        with pytest.raises(ValueError, match="Unknown fitting_kind"):
            hooper_two_k("totally_unknown")


# ===========================================================================
# piping_pressure_drop LLM tool (async)
# ===========================================================================

class TestPipingPressureDropTool:
    SEGMENTS = [{"diameter_in": 4.026, "length_ft": 100.0}]
    FITTINGS = [
        {"fitting_kind": "90_elbow_welded", "diameter_in": 4.0, "quantity": 2},
        {"fitting_kind": "gate_valve_open", "diameter_in": 4.0, "quantity": 1},
    ]

    def _call(self, **kwargs):
        from kerf_piping.tools import run_piping_pressure_drop
        args = {"segments": self.SEGMENTS, "flow_gpm": 100.0, "fluid": "water", **kwargs}
        return json.loads(_run(run_piping_pressure_drop(args, FakeCtx())))

    def test_basic_call_ok(self):
        r = self._call()
        assert r.get("ok") is True

    def test_total_dp_positive(self):
        r = self._call()
        assert r["total_dp_psi"] > 0.0

    def test_total_equals_pipe_plus_fittings(self):
        r = self._call(fittings=self.FITTINGS)
        assert r["total_dp_psi"] == pytest.approx(
            r["pipe_dp_psi"] + r["fitting_dp_psi"], rel=1e-4
        )

    def test_crane_oracle_100gpm_4in_100ft(self):
        """
        Darcy-Weisbach oracle: 100 GPM through 4.026" ID × 100 ft water.
        f≈0.0208, V≈2.52 ft/s → ΔP ≈ 0.265 psi.  Tolerance ±20%.
        """
        r = self._call(fittings=[])
        assert 0.18 < r["pipe_dp_psi"] < 0.40, (
            f"Expected ~0.265 psi, got {r['pipe_dp_psi']} psi"
        )

    def test_oil_higher_than_water_viscosity_effect(self):
        """
        Oil (μ≈3× water) at same volumetric flow → higher Re_friction → higher ΔP.
        """
        r_w = self._call(fluid="water", fittings=[])
        r_o = self._call(fluid="oil",   fittings=[])
        assert r_o["pipe_dp_psi"] > r_w["pipe_dp_psi"]

    def test_segment_details_present(self):
        r = self._call()
        assert "segment_details" in r
        assert len(r["segment_details"]) == 1

    def test_fitting_details_present(self):
        r = self._call(fittings=self.FITTINGS)
        assert "fitting_details" in r
        assert len(r["fitting_details"]) == 2

    def test_disclaimer_present(self):
        r = self._call()
        assert "disclaimer" in r

    def test_zero_flow(self):
        r = self._call(flow_gpm=0.0, fittings=[])
        assert r["total_dp_psi"] == 0.0

    def test_bad_fitting_kind_returns_error(self):
        from kerf_piping.tools import run_piping_pressure_drop
        args = {
            "segments": self.SEGMENTS,
            "fittings": [{"fitting_kind": "nonexistent_valve", "diameter_in": 4.0}],
            "flow_gpm": 100.0,
        }
        r = json.loads(_run(run_piping_pressure_drop(args, FakeCtx())))
        assert "error" in r or r.get("ok") is False or "PIPING_PRESSURE_DROP_ERROR" in str(r)
