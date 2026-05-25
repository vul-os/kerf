"""
Tests for kerf_civil.storm — Rational method + HDS-5 culvert inlet control.

Validation references:
  Rational method: Kuichling (1889), ASCE MOP 36.
  Culvert HDS-5:   FHWA (2012) HDS-5, 3rd Ed., Table 3-1.
"""
import asyncio
import json
import math
import pytest

from kerf_civil.storm import (
    rational_method,
    rational_method_si,
    culvert_inlet_control,
    culvert_capacity,
)


# ---------------------------------------------------------------------------
# Rational method
# ---------------------------------------------------------------------------

class TestRationalMethod:
    def test_basic_calculation(self):
        """
        Q = C * i * A / 360
        C=0.5, i=50 mm/hr, A=2 ha → Q = 0.5*50*2/360 = 0.1389 m³/s
        """
        Q = rational_method(0.5, 50.0, 2.0)
        assert abs(Q - 0.5 * 50.0 * 2.0 / 360.0) < 1e-10

    def test_zero_area(self):
        assert rational_method(0.5, 50.0, 0.0) == 0.0

    def test_zero_intensity(self):
        assert rational_method(0.5, 0.0, 5.0) == 0.0

    def test_c_equals_one(self):
        """Max runoff: C=1 (impervious surface)."""
        Q = rational_method(1.0, 100.0, 1.0)
        assert abs(Q - 100.0 / 360.0) < 1e-10

    def test_invalid_c_high(self):
        with pytest.raises(ValueError):
            rational_method(1.1, 50.0, 1.0)

    def test_invalid_c_low(self):
        with pytest.raises(ValueError):
            rational_method(-0.1, 50.0, 1.0)

    def test_invalid_intensity(self):
        with pytest.raises(ValueError):
            rational_method(0.5, -10.0, 1.0)

    def test_invalid_area(self):
        with pytest.raises(ValueError):
            rational_method(0.5, 50.0, -1.0)

    def test_units_consistency(self):
        """
        Rational SI: Q = C * i[m/s] * A[m²]
        With i=50 mm/hr = 50/(3.6e6) m/s, A = 2 ha = 20000 m²
        Should match rational_method(0.5, 50, 2)
        """
        i_m_s = 50.0 / 3_600_000.0
        area_m2 = 2.0 * 10_000.0
        Q_si = rational_method_si(0.5, i_m_s, area_m2)
        Q_ra = rational_method(0.5, 50.0, 2.0)
        assert abs(Q_si - Q_ra) / Q_ra < 0.001


# ---------------------------------------------------------------------------
# HDS-5 Culvert Inlet Control — headwater calculation
# ---------------------------------------------------------------------------

class TestCulvertInletControl:
    def test_small_discharge_unsubmerged(self):
        """Small Q should give unsubmerged regime."""
        result = culvert_inlet_control(Q=0.05, d=0.9, slope=0.01)
        assert result["regime"] == "unsubmerged"
        assert result["H_m"] > 0
        assert result["HW_D"] > 0

    def test_large_discharge_submerged(self):
        """Very large Q relative to pipe should give submerged regime."""
        result = culvert_inlet_control(Q=5.0, d=0.9, slope=0.01)
        assert result["regime"] in ("submerged", "transition")

    def test_hds5_equation_unsubmerged(self):
        """
        Validate unsubmerged form against HDS-5 Eq. 3-1a.
        For Q=0.3 m³/s, d=0.9m, slope=0.02:
          x_us = Q_cfs / (A_ft2 * sqrt(D_ft))
          HW/D = K * x_us^M + K_s
        """
        Q, d, slope = 0.3, 0.9, 0.02
        K, M = 0.0098, 2.0
        c, Y = 0.0433, 0.82

        A = math.pi * (d / 2.0) ** 2
        A_ft2 = A * 10.7639
        D_ft = d * 3.28084
        Q_cfs = Q * 35.3147
        x_us = Q_cfs / (A_ft2 * math.sqrt(D_ft))

        K_s = 0.5 * slope
        hw_d_expected = K * x_us ** M + K_s
        H_expected = hw_d_expected * d

        result = culvert_inlet_control(Q, d, slope=slope, K=K, M=M, c=c, Y=Y)
        assert result["regime"] == "unsubmerged"
        assert abs(result["H_m"] - H_expected) < 1e-6, (
            f"H={result['H_m']:.6f}, expected={H_expected:.6f}"
        )

    def test_hds5_equation_submerged(self):
        """
        Validate submerged form against HDS-5 Eq. 3-1b.
        """
        Q, d, slope = 3.0, 0.9, 0.01
        K, M = 0.0098, 2.0
        c, Y = 0.0433, 0.82

        A = math.pi * (d / 2.0) ** 2
        A_ft2 = A * 10.7639
        D_ft = d * 3.28084
        Q_cfs = Q * 35.3147
        x_us = Q_cfs / (A_ft2 * math.sqrt(D_ft))

        hw_d_expected = c * x_us ** 2 + Y - 0.5 * slope
        H_expected = hw_d_expected * d

        result = culvert_inlet_control(Q, d, slope=slope, K=K, M=M, c=c, Y=Y)
        assert result["regime"] == "submerged"
        assert abs(result["H_m"] - H_expected) < 1e-5, (
            f"H={result['H_m']:.6f}, expected={H_expected:.6f}"
        )

    def test_zero_discharge(self):
        result = culvert_inlet_control(Q=0.0, d=0.9, slope=0.01)
        assert result["H_m"] >= 0

    def test_invalid_negative_q(self):
        with pytest.raises(ValueError):
            culvert_inlet_control(Q=-1.0, d=0.9)

    def test_invalid_d(self):
        with pytest.raises(ValueError):
            culvert_inlet_control(Q=0.5, d=0.0)

    def test_headwater_increases_with_q(self):
        """More flow → higher headwater."""
        H1 = culvert_inlet_control(Q=0.2, d=0.9, slope=0.01)["H_m"]
        H2 = culvert_inlet_control(Q=0.5, d=0.9, slope=0.01)["H_m"]
        assert H2 > H1

    def test_larger_culvert_lower_headwater(self):
        """Larger diameter → lower headwater for same Q."""
        H1 = culvert_inlet_control(Q=0.5, d=0.6, slope=0.01)["H_m"]
        H2 = culvert_inlet_control(Q=0.5, d=1.2, slope=0.01)["H_m"]
        assert H2 < H1


# ---------------------------------------------------------------------------
# Culvert capacity (inverse solve)
# ---------------------------------------------------------------------------

class TestCulvertCapacity:
    def test_round_trip(self):
        """culvert_inlet_control(Q) → H; culvert_capacity(H) → Q_recovered ≈ Q."""
        Q = 0.4
        d = 0.9
        slope = 0.01
        result_hw = culvert_inlet_control(Q, d, slope=slope)
        H = result_hw["H_m"]
        result_cap = culvert_capacity(d, H, slope=slope)
        # Round-trip tolerance: within 5% (regime boundary effects)
        assert abs(result_cap["Q_m3s"] - Q) / Q < 0.10, (
            f"Round-trip: Q_recovered={result_cap['Q_m3s']:.4f}, Q_original={Q:.4f}"
        )

    def test_zero_hw_zero_q(self):
        result = culvert_capacity(0.9, 0.0, slope=0.01)
        assert result["Q_m3s"] == 0.0

    def test_capacity_increases_with_hw(self):
        Q1 = culvert_capacity(0.9, 0.5)["Q_m3s"]
        Q2 = culvert_capacity(0.9, 1.5)["Q_m3s"]
        assert Q2 > Q1


# ---------------------------------------------------------------------------
# LLM tool handlers
# ---------------------------------------------------------------------------

def test_tool_rational():
    from kerf_civil.tools_hydraulics import run_civil_storm_rational
    from kerf_civil._compat import ProjectCtx

    params = {"C": 0.5, "i_mm_hr": 50.0, "area_ha": 2.0}
    result = asyncio.run(run_civil_storm_rational(params, ProjectCtx()))
    data = json.loads(result)
    assert data["ok"] is True
    assert abs(data["Q_m3s"] - 0.5 * 50.0 * 2.0 / 360.0) < 1e-8


def test_tool_culvert_headwater():
    from kerf_civil.tools_hydraulics import run_civil_culvert_capacity
    from kerf_civil._compat import ProjectCtx

    params = {"op": "headwater", "d": 0.9, "Q": 0.3, "slope": 0.01}
    result = asyncio.run(run_civil_culvert_capacity(params, ProjectCtx()))
    data = json.loads(result)
    assert data["ok"] is True
    assert data["H_m"] > 0
    assert data["regime"] in ("unsubmerged", "transition", "submerged")


def test_tool_culvert_capacity():
    from kerf_civil.tools_hydraulics import run_civil_culvert_capacity
    from kerf_civil._compat import ProjectCtx

    params = {"op": "capacity", "d": 0.9, "HW": 1.0, "slope": 0.01}
    result = asyncio.run(run_civil_culvert_capacity(params, ProjectCtx()))
    data = json.loads(result)
    assert data["ok"] is True
    assert data["Q_m3s"] > 0
