"""Tests for fin_flutter.py — Barrowman fin flutter and CP/CG stability."""

from __future__ import annotations

import math
import pytest

from kerf_aero.fin_flutter import (
    fin_flutter_speed,
    FinFlutterResult,
    barrowman_cp,
    RocketStabilityResult,
)


class TestFinFlutterSpeed:
    """Validate fin flutter speed calculation against known references."""

    def test_aluminium_fin_sea_level(self):
        """Aluminium fin, AR≈1.6, t/c≈3%, sea level; flutter should be >> 100 m/s."""
        # Typical 1/4-scale rocket fin: 0.1 m semi-span, 0.08/0.04 m root/tip chord
        # Aluminium 6061: G ≈ 26 GPa; thickness 2 mm
        r = fin_flutter_speed(
            span=0.10,
            root_chord=0.08,
            tip_chord=0.04,
            thickness=0.002,
            shear_modulus=26e9,
        )
        assert r.flutter_speed_ms > 100.0, (
            f"Expected flutter speed > 100 m/s; got {r.flutter_speed_ms:.1f}"
        )
        assert r.mach_flutter > 0.0
        assert r.tc_ratio > 0

    def test_balsa_fin_low_flutter(self):
        """Thin balsa fin should have significantly lower flutter speed than aluminium."""
        r_alu = fin_flutter_speed(
            span=0.10, root_chord=0.08, tip_chord=0.04,
            thickness=0.002, shear_modulus=26e9,
        )
        # Balsa end-grain G ≈ 100 MPa
        r_balsa = fin_flutter_speed(
            span=0.10, root_chord=0.08, tip_chord=0.04,
            thickness=0.002, shear_modulus=100e6,
        )
        assert r_balsa.flutter_speed_ms < r_alu.flutter_speed_ms, (
            "Balsa fin should flutter at lower speed than aluminium"
        )

    def test_safety_margin(self):
        """Safety margin = flutter_speed / design_speed."""
        r = fin_flutter_speed(
            span=0.10, root_chord=0.08, tip_chord=0.04,
            thickness=0.002, shear_modulus=26e9,
            design_speed_ms=200.0,
        )
        expected_sm = r.flutter_speed_ms / 200.0
        assert abs(r.safety_margin - expected_sm) < 1e-9

    def test_no_design_speed_nan_margin(self):
        """Without design_speed, safety_margin is NaN."""
        r = fin_flutter_speed(
            span=0.10, root_chord=0.08, tip_chord=0.04,
            thickness=0.002, shear_modulus=26e9,
        )
        assert math.isnan(r.safety_margin)

    def test_higher_altitude_lower_density(self):
        """Higher altitude (lower density) → higher flutter speed."""
        r_sl = fin_flutter_speed(
            span=0.10, root_chord=0.08, tip_chord=0.04,
            thickness=0.002, shear_modulus=26e9, altitude=0.0,
        )
        r_hi = fin_flutter_speed(
            span=0.10, root_chord=0.08, tip_chord=0.04,
            thickness=0.002, shear_modulus=26e9, altitude=10000.0,
        )
        assert r_hi.flutter_speed_ms > r_sl.flutter_speed_ms, (
            "Flutter speed at 10 km should exceed sea level (lower density)"
        )

    def test_invalid_inputs(self):
        with pytest.raises(ValueError):
            fin_flutter_speed(span=-0.1, root_chord=0.08, tip_chord=0.04,
                              thickness=0.002, shear_modulus=26e9)
        with pytest.raises(ValueError):
            fin_flutter_speed(span=0.1, root_chord=0.08, tip_chord=0.04,
                              thickness=0.0, shear_modulus=26e9)
        with pytest.raises(ValueError):
            fin_flutter_speed(span=0.1, root_chord=0.08, tip_chord=-0.01,
                              thickness=0.002, shear_modulus=26e9)

    def test_triangular_fin_high_flutter(self):
        """Triangular fin (tip_chord=0) has effectively infinite flutter resistance."""
        r = fin_flutter_speed(
            span=0.10, root_chord=0.08, tip_chord=0.0,
            thickness=0.002, shear_modulus=26e9,
        )
        # lambda → 0 so (1+lam)²/lam² → ∞, flutter speed → ∞
        assert r.flutter_speed_ms > 10000.0, (
            f"Triangular fin: expected very high flutter speed; got {r.flutter_speed_ms:.1f}"
        )

    def test_g10_composite_fin(self):
        """G10/FR4 composite fin (G≈2.5GPa) returns finite positive flutter speed."""
        r = fin_flutter_speed(
            span=0.15, root_chord=0.12, tip_chord=0.06,
            thickness=0.003, shear_modulus=2.5e9,
        )
        assert r.flutter_speed_ms > 0
        assert math.isfinite(r.flutter_speed_ms)


class TestBarrowmanCP:
    """Validate Barrowman CP location and static margin."""

    def test_4fin_stable_rocket(self):
        """4-fin rocket with fins aft of CG should be stable (positive static margin)."""
        # Nominal stable sport rocket:
        # Body diameter 54mm, nose 0.3m, 4 × trapezoidal fins
        # fin root 0.15m, tip 0.08m, span 0.08m, LE sweep 30deg
        # fin root TE at 1.0m from nose, CG at 0.6m from nose
        r = barrowman_cp(
            nose_length=0.30,
            body_diameter=0.054,
            fin_span=0.08,
            fin_root_chord=0.15,
            fin_tip_chord=0.08,
            fin_sweep_le=30.0,
            n_fins=4,
            fin_root_trailing_edge_from_nose=1.0,
            cg_from_nose=0.60,
        )
        assert r.static_margin_cal > 0.5, (
            f"Expected stable static margin > 0.5 cal; got {r.static_margin_cal:.3f} cal"
        )
        assert r.cp_from_nose > r.cg_from_nose, (
            "CP must be aft of CG for stability"
        )

    def test_3fin_rocket(self):
        """3-fin rocket returns valid CP."""
        r = barrowman_cp(
            nose_length=0.20,
            body_diameter=0.038,
            fin_span=0.06,
            fin_root_chord=0.10,
            fin_tip_chord=0.05,
            fin_sweep_le=20.0,
            n_fins=3,
            fin_root_trailing_edge_from_nose=0.75,
            cg_from_nose=0.45,
        )
        assert r.cn_alpha_total > 0
        assert 0 < r.cp_from_nose < 1.5  # physically plausible

    def test_invalid_n_fins(self):
        with pytest.raises(ValueError):
            barrowman_cp(
                nose_length=0.3, body_diameter=0.054,
                fin_span=0.08, fin_root_chord=0.15, fin_tip_chord=0.08,
                fin_sweep_le=30.0, n_fins=2,  # < 3
                fin_root_trailing_edge_from_nose=1.0, cg_from_nose=0.6,
            )
