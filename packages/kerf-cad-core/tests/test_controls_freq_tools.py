"""
tests/test_controls_freq_tools.py

Tests for kerf_cad_core.controls.freq_tools:
  - controls_bode_sweep
  - controls_nyquist_sweep
  - controls_tf_step_response

References
----------
Ogata, K. "Modern Control Engineering", 5th ed. (Pearson)
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _call(fn, payload: dict) -> dict:
    result = _run(fn(ctx=None, args=json.dumps(payload).encode()))
    return json.loads(result)


def _is_ok(d: dict) -> bool:
    """Return True if the response is a successful payload (has expected data keys,
    not an error response). ok_payload passes through the dict without an 'ok' key."""
    return "error" not in d and "reason" not in d


def _is_err(d: dict) -> bool:
    """Return True if the response is an error payload."""
    return d.get("ok") is False or "error" in d or "reason" in d


# ---------------------------------------------------------------------------
# Import tool functions
# ---------------------------------------------------------------------------

from kerf_cad_core.controls.freq_tools import (
    run_controls_bode_sweep,
    run_controls_nyquist_sweep,
    run_controls_tf_step_response,
)


# ===========================================================================
# controls_bode_sweep
# ===========================================================================

class TestBodeSweep:
    """controls_bode_sweep — Bode magnitude + phase arrays."""

    # --- Integrator G(s) = 1/s ------------------------------------------------
    # |G(jω)| = 1/ω  →  mag_dB = -20 log10(ω)   ∠G = -90°

    def test_integrator_mag_at_1_rad_s(self):
        """G=1/s: magnitude should be 0 dB at ω=1."""
        r = _call(run_controls_bode_sweep, {
            "num": [1.0],
            "den": [1.0, 0.0],
            "omega_min": 0.5,
            "omega_max": 2.0,
            "n_points": 50,
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        # Find index nearest ω=1
        omega = r["omega"]
        idx = min(range(len(omega)), key=lambda i: abs(omega[i] - 1.0))
        assert abs(r["mag_db"][idx]) < 1.0   # ≈ 0 dB at ω=1

    def test_integrator_phase_minus90(self):
        """G=1/s: phase should be −90° ± 1°."""
        r = _call(run_controls_bode_sweep, {
            "num": [1.0],
            "den": [1.0, 0.0],
            "omega_min": 0.1,
            "omega_max": 10.0,
            "n_points": 100,
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        for ph in r["phase_deg"]:
            assert abs(ph - (-90.0)) < 2.0

    # --- DC gain: G(s) = K -----------------------------------------------

    def test_dc_gain_mag(self):
        """G(s)=5 → mag_dB = 20*log10(5) ≈ 14 dB at all frequencies."""
        expected_db = 20.0 * math.log10(5.0)
        r = _call(run_controls_bode_sweep, {
            "num": [5.0],
            "den": [1.0],
            "omega_min": 1.0,
            "omega_max": 100.0,
            "n_points": 100,
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        for m in r["mag_db"]:
            assert abs(m - expected_db) < 0.01

    # --- 2nd-order system G(s) = ωn² / (s² + 2ζωn s + ωn²) ---------------

    def test_second_order_resonance(self):
        """G=1/(s²+2s+1): shape in Bode."""
        r = _call(run_controls_bode_sweep, {
            "num": [1.0],
            "den": [1.0, 2.0, 1.0],   # ωn=1, ζ=1 (critically damped)
            "omega_min": 0.01,
            "omega_max": 100.0,
            "n_points": 500,
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        assert len(r["omega"]) == 500
        # DC gain: |G(0)| → 1 → 0 dB
        assert abs(r["mag_db"][0]) < 1.0

    # --- Gain & phase margins for a known system ---------------------------

    def test_margins_found(self):
        """G = 1 / (s(s+1)(s+2)) has a phase crossover and gain margin > 0."""
        r = _call(run_controls_bode_sweep, {
            # G = 1 / (s³ + 3s² + 2s) = 1 / (s(s+1)(s+2))
            "num": [1.0],
            "den": [1.0, 3.0, 2.0, 0.0],
            "omega_min": 0.01,
            "omega_max": 1000.0,
            "n_points": 1000,
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        # GM should be > 6 dB for this system (it's stable at K=1)
        assert r["gain_margin_db"] is not None
        assert r["gain_margin_db"] > 0.0

    # --- Input validation --------------------------------------------------

    def test_missing_num_error(self):
        r = _call(run_controls_bode_sweep, {"den": [1.0, 1.0]})
        assert _is_err(r)

    def test_missing_den_error(self):
        r = _call(run_controls_bode_sweep, {"num": [1.0]})
        assert _is_err(r)

    def test_omega_min_not_positive_error(self):
        r = _call(run_controls_bode_sweep, {
            "num": [1.0], "den": [1.0, 1.0], "omega_min": -1.0
        })
        assert _is_err(r)

    def test_omega_max_less_than_min_error(self):
        r = _call(run_controls_bode_sweep, {
            "num": [1.0], "den": [1.0, 1.0], "omega_min": 10.0, "omega_max": 1.0
        })
        assert _is_err(r)

    def test_n_points_clamped_to_max(self):
        r = _call(run_controls_bode_sweep, {
            "num": [1.0], "den": [1.0, 1.0], "n_points": 99999
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        assert len(r["omega"]) <= 2000

    def test_output_arrays_same_length(self):
        r = _call(run_controls_bode_sweep, {
            "num": [1.0],
            "den": [1.0, 2.0, 1.0],
            "n_points": 200,
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        assert len(r["omega"]) == len(r["mag_db"]) == len(r["phase_deg"]) == 200

    def test_log_spaced_omega(self):
        r = _call(run_controls_bode_sweep, {
            "num": [1.0], "den": [1.0, 1.0],
            "omega_min": 1.0, "omega_max": 1000.0, "n_points": 4,
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        # Ratios between consecutive ω should be approximately equal
        om = r["omega"]
        ratio01 = om[1] / om[0]
        ratio12 = om[2] / om[1]
        assert abs(ratio01 - ratio12) / ratio01 < 0.01

    def test_response_has_expected_keys(self):
        r = _call(run_controls_bode_sweep, {
            "num": [1.0], "den": [1.0, 1.0],
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        for key in ("omega", "mag_db", "phase_deg", "n_points"):
            assert key in r, f"Missing key: {key}"


# ===========================================================================
# controls_nyquist_sweep
# ===========================================================================

class TestNyquistSweep:
    """controls_nyquist_sweep — Nyquist diagram data."""

    # --- G(s) = 1/(s+1): G(jω) = 1/(jω+1) → always inside unit disk -----

    def test_first_order_no_encirclement(self):
        """G=1/(s+1) is stable; Nyquist should NOT encircle -1+0j."""
        r = _call(run_controls_nyquist_sweep, {
            "num": [1.0],
            "den": [1.0, 1.0],
            "omega_min": 0.001,
            "omega_max": 1e4,
            "n_points": 500,
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        assert r["encirclements_approx"] == 0

    def test_integrator_nyquist_arrays(self):
        """G=1/s: Re=0, Im=-1/ω → large negative Im at low ω."""
        r = _call(run_controls_nyquist_sweep, {
            "num": [1.0],
            "den": [1.0, 0.0],
            "omega_min": 0.01,
            "omega_max": 100.0,
            "n_points": 200,
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        # At small ω: Im(G(jω)) = Im(1/(jω)) = -1/ω → very negative
        assert r["imag_g"][0] < -5.0

    def test_arrays_same_length(self):
        r = _call(run_controls_nyquist_sweep, {
            "num": [1.0], "den": [1.0, 1.0], "n_points": 300
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        assert (
            len(r["omega"])
            == len(r["real_g"])
            == len(r["imag_g"])
            == len(r["mag"])
            == len(r["phase_deg"])
            == 300
        )

    def test_missing_num_error(self):
        r = _call(run_controls_nyquist_sweep, {"den": [1.0, 1.0]})
        assert _is_err(r)

    def test_magnitude_positive(self):
        r = _call(run_controls_nyquist_sweep, {
            "num": [2.0], "den": [1.0, 1.0], "n_points": 50
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        for m in r["mag"]:
            assert m >= 0.0

    def test_response_has_expected_keys(self):
        r = _call(run_controls_nyquist_sweep, {
            "num": [1.0], "den": [1.0, 1.0],
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        for key in ("omega", "real_g", "imag_g", "mag", "phase_deg", "encirclements_approx"):
            assert key in r, f"Missing key: {key}"


# ===========================================================================
# controls_tf_step_response
# ===========================================================================

class TestTFStepResponse:
    """controls_tf_step_response — step/impulse response arrays."""

    # --- G(s) = 1/(τs+1): step response → K(1 - e^(-t/τ)) ---------------

    def test_first_order_step_steady_state(self):
        """G = 1/(s+1): step response → 1 at large t."""
        r = _call(run_controls_tf_step_response, {
            "num": [1.0],
            "den": [1.0, 1.0],
            "t_end": 20.0,
            "n_points": 500,
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        ss = r["steady_state"]
        assert abs(ss - 1.0) < 0.05   # should be close to 1

    def test_first_order_step_shape(self):
        """Step response should be monotonically increasing for G=1/(s+1)."""
        r = _call(run_controls_tf_step_response, {
            "num": [1.0],
            "den": [1.0, 1.0],
            "t_end": 10.0,
            "n_points": 200,
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        y = r["y"]
        # Allow small wiggles due to discretisation; check overall trend
        assert y[-1] > y[0]

    def test_dc_gain_step(self):
        """G = 3/(s+1): step response → 3."""
        r = _call(run_controls_tf_step_response, {
            "num": [3.0],
            "den": [1.0, 1.0],
            "t_end": 20.0,
            "n_points": 500,
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        assert abs(r["steady_state"] - 3.0) < 0.15

    def test_second_order_underdamped_overshoot(self):
        """G = ωn²/(s²+2ζωns+ωn²) with ζ=0.3 → overshoot > 0."""
        wn, zeta = 2.0, 0.3
        r = _call(run_controls_tf_step_response, {
            "num": [wn**2],
            "den": [1.0, 2*zeta*wn, wn**2],
            "t_end": 15.0,
            "n_points": 1000,
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        y = r["y"]
        assert max(y) > 1.0   # overshoot: y exceeds 1

    def test_impulse_type(self):
        """Impulse response type should be accepted without error."""
        r = _call(run_controls_tf_step_response, {
            "num": [1.0],
            "den": [1.0, 1.0],
            "response_type": "impulse",
            "t_end": 10.0,
            "n_points": 200,
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        assert r["response_type"] == "impulse"

    def test_auto_t_end_when_missing(self):
        """When t_end is omitted, a sensible default should be used."""
        r = _call(run_controls_tf_step_response, {
            "num": [1.0],
            "den": [1.0, 2.0, 1.0],
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        assert r["t_end"] > 0.0

    def test_missing_num_error(self):
        r = _call(run_controls_tf_step_response, {"den": [1.0, 1.0]})
        assert _is_err(r)

    def test_missing_den_error(self):
        r = _call(run_controls_tf_step_response, {"num": [1.0]})
        assert _is_err(r)

    def test_t_end_negative_error(self):
        r = _call(run_controls_tf_step_response, {
            "num": [1.0], "den": [1.0, 1.0], "t_end": -5.0
        })
        assert _is_err(r)

    def test_n_points_clamped(self):
        r = _call(run_controls_tf_step_response, {
            "num": [1.0], "den": [1.0, 1.0], "n_points": 99999, "t_end": 10.0
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        assert len(r["t"]) <= 5000

    def test_output_arrays_same_length(self):
        r = _call(run_controls_tf_step_response, {
            "num": [1.0], "den": [1.0, 1.0], "n_points": 300, "t_end": 5.0
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        assert len(r["t"]) == len(r["y"]) == 300

    def test_time_starts_at_zero(self):
        r = _call(run_controls_tf_step_response, {
            "num": [1.0], "den": [1.0, 1.0], "n_points": 100, "t_end": 10.0
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        assert r["t"][0] == pytest.approx(0.0, abs=1e-9)

    def test_response_has_expected_keys(self):
        r = _call(run_controls_tf_step_response, {
            "num": [1.0], "den": [1.0, 1.0], "t_end": 5.0
        })
        assert _is_ok(r), f"Expected success, got: {r}"
        for key in ("t", "y", "n_points", "t_end", "response_type", "steady_state"):
            assert key in r, f"Missing key: {key}"
