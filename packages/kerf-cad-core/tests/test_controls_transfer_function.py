"""
Tests for kerf_cad_core.controls.transfer_function

Coverage:
  TransferFunction evaluation, poles, zeros
  Bode plot data
  Nyquist data
  Routh-Hurwitz stability
  Gain/phase margins
  Feedback interconnection
  Arithmetic (series, parallel)

All tests are pure-Python + numpy, hermetic (no network/DB/OCC).

References: Ogata (2010); Routh (1877); Hurwitz (1895); Nyquist (1932).
"""
from __future__ import annotations

import math
import cmath
import numpy as np
import pytest

from kerf_cad_core.controls.transfer_function import (
    TransferFunction,
    routh_hurwitz,
    bode_plot_data,
    nyquist_plot_data,
    gain_phase_margin,
    feedback,
)


# ---------------------------------------------------------------------------
# 1. TransferFunction construction and evaluation
# ---------------------------------------------------------------------------

class TestTransferFunctionEval:
    def test_eval_at_zero_unit_tf(self):
        """G=1/(s²+s+1) at s=0 → 1."""
        tf = TransferFunction(num=[1.0], den=[1.0, 1.0, 1.0])
        result = tf.evaluate_at(complex(0.0))
        assert abs(result - 1.0) < 1e-10

    def test_eval_at_s1(self):
        """G=1/s at s=1 → 1."""
        tf = TransferFunction(num=[1.0], den=[1.0, 0.0])
        result = tf.evaluate_at(complex(1.0))
        assert abs(result - 1.0) < 1e-10

    def test_eval_integrator_at_j(self):
        """G=1/s at s=j → -j."""
        tf = TransferFunction(num=[1.0], den=[1.0, 0.0])
        result = tf.evaluate_at(complex(0.0, 1.0))
        expected = -1j
        assert abs(result - expected) < 1e-10

    def test_poles_second_order(self):
        """G=1/(s²+s+1): poles at (-0.5 ± j√3/2)."""
        tf = TransferFunction(num=[1.0], den=[1.0, 1.0, 1.0])
        poles = tf.poles()
        assert len(poles) == 2
        real_parts = sorted([p.real for p in poles])
        assert abs(real_parts[0] - (-0.5)) < 1e-8
        assert abs(real_parts[1] - (-0.5)) < 1e-8

    def test_zeros_numerator(self):
        """G=(s+2)/(s+1): zeros at s=-2."""
        tf = TransferFunction(num=[1.0, 2.0], den=[1.0, 1.0])
        zeros = tf.zeros()
        assert len(zeros) == 1
        assert abs(zeros[0] - (-2.0)) < 1e-8

    def test_construction_rejects_zero_leading_den(self):
        """Leading denominator coefficient must be non-zero."""
        with pytest.raises(ValueError):
            TransferFunction(num=[1.0], den=[0.0, 1.0, 1.0])

    def test_series_multiplication(self):
        """G1*G2 = (1/(s+1)) * (1/(s+2)) = 1/((s+1)(s+2))."""
        g1 = TransferFunction(num=[1.0], den=[1.0, 1.0])
        g2 = TransferFunction(num=[1.0], den=[1.0, 2.0])
        g = g1 * g2
        # Evaluate at s=0: should be 1/(1*2) = 0.5
        assert abs(g.evaluate_at(complex(0.0)) - 0.5) < 1e-10


# ---------------------------------------------------------------------------
# 2. Routh-Hurwitz
# ---------------------------------------------------------------------------

class TestRouthHurwitz:
    def test_stable_second_order(self):
        """G=1/(s²+s+1): all coefficients positive → stable."""
        result = routh_hurwitz([1.0, 1.0, 1.0])
        assert result["stable"] is True
        assert result["sign_changes"] == 0
        assert result["right_half_plane_poles"] == 0

    def test_unstable_negative_coeff(self):
        """G=1/(s²-s-1): mixed signs → unstable, sign changes > 0."""
        result = routh_hurwitz([1.0, -1.0, -1.0])
        assert result["stable"] is False
        assert result["sign_changes"] > 0

    def test_first_column_all_positive_stable(self):
        """Stable 3rd order: s³+6s²+11s+6 → first column all positive."""
        result = routh_hurwitz([1.0, 6.0, 11.0, 6.0])
        assert result["stable"] is True
        fc = result["first_column"]
        assert all(v > 0 for v in fc), f"First column: {fc}"

    def test_unstable_rhp_count(self):
        """Polynomial s³-3s+2 = (s-1)²(s+2): 2 RHP roots."""
        # Coefficients: 1, 0, -3, 2
        result = routh_hurwitz([1.0, 0.0, -3.0, 2.0])
        assert result["stable"] is False

    def test_marginal_stability_warning(self):
        """s²+1 (purely imaginary roots): first column sign changes edge case."""
        result = routh_hurwitz([1.0, 0.0, 1.0])
        # near-zero pivot expected — should return a result without raising
        assert "stable" in result

    def test_degree_one(self):
        """s+1: trivially stable."""
        result = routh_hurwitz([1.0, 1.0])
        assert result["stable"] is True
        assert result["sign_changes"] == 0


# ---------------------------------------------------------------------------
# 3. Bode plot data
# ---------------------------------------------------------------------------

class TestBodePlotData:
    def test_integrator_mag_at_high_freq(self):
        """G=1/s: at ω=10, |G|=1/10 → magnitude_dB ≈ -20 dB."""
        tf = TransferFunction(num=[1.0], den=[1.0, 0.0])
        omega = np.array([10.0])
        mag_db, phase_deg = bode_plot_data(tf, omega)
        assert abs(mag_db[0] - (-20.0)) < 0.5

    def test_integrator_phase(self):
        """G=1/s: phase = -90° for all ω."""
        tf = TransferFunction(num=[1.0], den=[1.0, 0.0])
        omega = np.array([1.0, 10.0, 100.0])
        _, phase_deg = bode_plot_data(tf, omega)
        for p in phase_deg:
            assert abs(p - (-90.0)) < 1.0

    def test_unity_gain_dc(self):
        """G=2: magnitude = 20*log10(2) ≈ 6 dB at all ω."""
        tf = TransferFunction(num=[2.0], den=[1.0])
        omega = np.array([1.0])
        mag_db, _ = bode_plot_data(tf, omega)
        assert abs(mag_db[0] - 20.0 * math.log10(2.0)) < 1e-6

    def test_bode_array_length(self):
        """Output arrays have same length as input omega."""
        tf = TransferFunction(num=[1.0], den=[1.0, 1.0])
        omega = np.logspace(-2, 3, 50)
        mag_db, phase_deg = bode_plot_data(tf, omega)
        assert len(mag_db) == 50
        assert len(phase_deg) == 50


# ---------------------------------------------------------------------------
# 4. Nyquist plot data
# ---------------------------------------------------------------------------

class TestNyquistPlotData:
    def test_nyquist_returns_complex_array(self):
        """nyquist_plot_data returns complex-valued array."""
        tf = TransferFunction(num=[1.0], den=[1.0, 1.0])
        omega = np.logspace(-2, 2, 100)
        result = nyquist_plot_data(tf, omega)
        assert result.dtype == complex
        assert len(result) == 100

    def test_nyquist_integrator_real_zero(self):
        """G=1/s: Re[G(jω)]=0 for all ω."""
        tf = TransferFunction(num=[1.0], den=[1.0, 0.0])
        omega = np.array([1.0, 2.0, 5.0])
        result = nyquist_plot_data(tf, omega)
        for g in result:
            assert abs(g.real) < 1e-10

    def test_nyquist_dc_gain(self):
        """G=2/(s+1): as ω→0, G(j0)=2/(0+1)=2 (real)."""
        tf = TransferFunction(num=[2.0], den=[1.0, 1.0])
        omega = np.array([1e-6])
        result = nyquist_plot_data(tf, omega)
        assert abs(result[0].real - 2.0) < 0.01
        assert abs(result[0].imag) < 0.01


# ---------------------------------------------------------------------------
# 5. Gain/phase margin
# ---------------------------------------------------------------------------

class TestGainPhaseMargin:
    def test_margins_finite_positive_stable(self):
        """G=10/(s³+6s²+11s+6): finite positive GM and PM for stable loop."""
        tf = TransferFunction(num=[10.0], den=[1.0, 6.0, 11.0, 6.0])
        result = gain_phase_margin(tf)
        gm = result["gain_margin_db"]
        pm = result["phase_margin_deg"]
        # Both should be finite and positive (stable system)
        assert gm is not None and math.isfinite(gm) and gm > 0, f"GM={gm}"
        assert pm is not None and math.isfinite(pm) and pm > 0, f"PM={pm}"

    def test_margins_keys_present(self):
        """Result dict contains expected keys."""
        tf = TransferFunction(num=[1.0], den=[1.0, 3.0, 2.0])
        result = gain_phase_margin(tf)
        for key in ("gain_margin_db", "phase_margin_deg", "omega_gc", "omega_pc"):
            assert key in result


# ---------------------------------------------------------------------------
# 6. Feedback interconnection
# ---------------------------------------------------------------------------

class TestFeedback:
    def test_unity_negative_feedback(self):
        """T = G/(1+G) for G=1/(s+1), H=1 → 1/(s+2)."""
        G = TransferFunction(num=[1.0], den=[1.0, 1.0])
        H = TransferFunction(num=[1.0], den=[1.0])
        T = feedback(G, H, sign=-1.0)
        # T(0) = (1/(1))/(1+1/(1)) = 0.5
        assert abs(T.evaluate_at(complex(0.0)) - 0.5) < 1e-8

    def test_feedback_dc_gain(self):
        """T(0) = G(0)/(1 + G(0)*H(0)) for DC."""
        G = TransferFunction(num=[2.0], den=[1.0, 1.0])  # G(0) = 2
        H = TransferFunction(num=[1.0], den=[1.0])        # H(0) = 1
        T = feedback(G, H, sign=-1.0)
        expected = 2.0 / (1.0 + 2.0 * 1.0)
        actual = T.evaluate_at(complex(0.0)).real
        assert abs(actual - expected) < 1e-6
