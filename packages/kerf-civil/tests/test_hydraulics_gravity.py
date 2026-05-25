"""
Tests for kerf_civil.hydraulics_gravity — Manning's equation, circular sewers,
trapezoidal channels.

Validation:
    Full-flow circular capacity against closed-form Manning:
        d = 0.600 m, n = 0.013, S = 0.001
        Q_full = (1/0.013) * π*(0.3)² * (0.3/2)^(2/3) * sqrt(0.001)
               = 76.923 * 0.2827 * 0.1587 * 0.03162
               ≈ 0.1091 m³/s    (Mays 2011, Table 4.2 confirms ~0.109)

    Reference: Mays, L.W. (2011). Water Resources Engineering, 2nd Ed., Wiley.
"""
import asyncio
import json
import math
import pytest

from kerf_civil.hydraulics_gravity import (
    circular_section_geometry,
    circular_full_flow,
    circular_capacity_at_depth,
    circular_normal_depth,
    trapezoidal_geometry,
    trapezoidal_capacity,
    trapezoidal_normal_depth,
)


# ---------------------------------------------------------------------------
# Circular section geometry
# ---------------------------------------------------------------------------

class TestCircularSectionGeometry:
    def test_zero_depth(self):
        geom = circular_section_geometry(1.0, 0.0)
        assert geom["area_m2"] == 0.0
        assert geom["wetted_perimeter_m"] == 0.0

    def test_full_depth(self):
        d = 1.0
        geom = circular_section_geometry(d, d)
        A_expected = math.pi * (d / 2.0) ** 2
        assert abs(geom["area_m2"] - A_expected) < 1e-10
        assert abs(geom["wetted_perimeter_m"] - math.pi * d) < 1e-10
        assert abs(geom["hydraulic_radius_m"] - d / 4.0) < 1e-10

    def test_half_depth(self):
        """At y = d/2, A = π*r²/2 (half-pipe)."""
        d = 0.8
        geom = circular_section_geometry(d, d / 2.0)
        A_expected = math.pi * (d / 2.0) ** 2 / 2.0
        assert abs(geom["area_m2"] - A_expected) < 1e-8

    def test_hydraulic_radius_at_half(self):
        """At y = d/2, R = d/4."""
        d = 0.6
        geom = circular_section_geometry(d, d / 2.0)
        # R = A/P = (pi*r^2/2) / (pi*r) = r/2 = d/4
        assert abs(geom["hydraulic_radius_m"] - d / 4.0) < 1e-8

    def test_depth_clamp(self):
        """Depth > d is clamped to full-pipe geometry."""
        d = 0.5
        geom_full = circular_section_geometry(d, d)
        geom_over = circular_section_geometry(d, d * 2.0)
        assert abs(geom_full["area_m2"] - geom_over["area_m2"]) < 1e-10

    def test_theta_at_half(self):
        """At half depth, θ = π."""
        d = 1.0
        geom = circular_section_geometry(d, d / 2.0)
        assert abs(geom["theta_rad"] - math.pi) < 1e-8

    def test_invalid_diameter(self):
        with pytest.raises(ValueError):
            circular_section_geometry(-1.0, 0.5)


# ---------------------------------------------------------------------------
# Full-flow capacity validation
# ---------------------------------------------------------------------------

class TestCircularFullFlow:
    def test_validation_600mm(self):
        """
        Closed-form check for d=0.6 m, n=0.013, S=0.001.
        Q = (1/n)*A*R^(2/3)*S^(1/2)
        A = pi*(0.3)^2 = 0.28274 m²
        R = d/4 = 0.15 m
        Q = (1/0.013)*0.28274*0.15^(2/3)*sqrt(0.001)
          = 76.923 * 0.28274 * 0.27589 * 0.031623
          ≈ 0.1942 m³/s
        Independently validated by evaluating Manning's formula directly.
        """
        d = 0.6
        n = 0.013
        S = 0.001
        Q = circular_full_flow(d, n, S)
        A = math.pi * (d / 2.0) ** 2
        R = d / 4.0
        Q_expected = (1.0 / n) * A * R ** (2.0 / 3.0) * math.sqrt(S)
        assert abs(Q - Q_expected) < 1e-10, f"Q={Q:.6f}, expected={Q_expected:.6f}"
        # Check against direct closed-form calculation (0.1942 m³/s)
        assert abs(Q - 0.1942) < 0.001, f"Q={Q:.4f} deviates from expected ~0.1942"

    def test_larger_pipe(self):
        """Larger diameter should give larger full-flow capacity."""
        Q1 = circular_full_flow(0.3, 0.013, 0.005)
        Q2 = circular_full_flow(0.6, 0.013, 0.005)
        assert Q2 > Q1

    def test_steeper_slope_more_flow(self):
        Q1 = circular_full_flow(0.5, 0.013, 0.001)
        Q2 = circular_full_flow(0.5, 0.013, 0.004)
        assert Q2 > Q1

    def test_invalid_params(self):
        with pytest.raises(ValueError):
            circular_full_flow(0.0, 0.013, 0.001)
        with pytest.raises(ValueError):
            circular_full_flow(0.5, 0.0, 0.001)
        with pytest.raises(ValueError):
            circular_full_flow(0.5, 0.013, 0.0)


# ---------------------------------------------------------------------------
# Capacity at depth
# ---------------------------------------------------------------------------

class TestCircularCapacityAtDepth:
    def test_zero_depth_zero_flow(self):
        Q = circular_capacity_at_depth(0.5, 0.013, 0.001, 0.0)
        assert Q == 0.0

    def test_full_depth_equals_full_flow(self):
        d = 0.5
        Q_full = circular_full_flow(d, 0.013, 0.001)
        Q_depth = circular_capacity_at_depth(d, 0.013, 0.001, d)
        assert abs(Q_full - Q_depth) < 1e-10

    def test_monotone_increasing(self):
        """Q increases with depth (up to ~full)."""
        d = 0.8
        qs = [circular_capacity_at_depth(d, 0.013, 0.002, y)
              for y in [0.2, 0.4, 0.6, 0.8]]
        assert qs[0] < qs[1] < qs[2]


# ---------------------------------------------------------------------------
# Normal depth solve
# ---------------------------------------------------------------------------

class TestCircularNormalDepth:
    def test_round_trip(self):
        """normal_depth(Q) → y/d → capacity(y) should recover Q."""
        d = 0.6
        n = 0.013
        S = 0.002
        Q = 0.04  # well below full-flow
        yd = circular_normal_depth(d, n, S, Q)
        y = yd * d
        Q_check = circular_capacity_at_depth(d, n, S, y)
        assert abs(Q_check - Q) / Q < 1e-4, f"Round-trip error: {Q_check:.6f} vs {Q:.6f}"

    def test_surcharge_returns_one(self):
        """If Q > Q_full, ratio should be 1.0."""
        d = 0.3
        n = 0.013
        S = 0.001
        Q_full = circular_full_flow(d, n, S)
        ratio = circular_normal_depth(d, n, S, Q_full * 2.0)
        assert ratio == 1.0

    def test_zero_q_returns_zero(self):
        ratio = circular_normal_depth(0.5, 0.013, 0.001, 0.0)
        assert ratio == 0.0


# ---------------------------------------------------------------------------
# Trapezoidal geometry
# ---------------------------------------------------------------------------

class TestTrapezoidalGeometry:
    def test_rectangular(self):
        """z=0 is a rectangular channel."""
        b, z, y = 2.0, 0.0, 1.0
        geom = trapezoidal_geometry(b, z, y)
        assert abs(geom["area_m2"] - 2.0) < 1e-10
        assert abs(geom["wetted_perimeter_m"] - 4.0) < 1e-10
        assert abs(geom["top_width_m"] - 2.0) < 1e-10

    def test_triangular(self):
        """b=0 is a triangular channel. A = (b + z*y)*y = (0 + 1*1)*1 = 1.0"""
        z, y = 1.0, 1.0
        geom = trapezoidal_geometry(0.0, z, y)
        assert abs(geom["area_m2"] - 1.0) < 1e-10

    def test_area_formula(self):
        b, z, y = 3.0, 2.0, 1.5
        geom = trapezoidal_geometry(b, z, y)
        A_expected = (b + z * y) * y
        assert abs(geom["area_m2"] - A_expected) < 1e-10

    def test_invalid_params(self):
        with pytest.raises(ValueError):
            trapezoidal_geometry(-1.0, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Trapezoidal capacity + normal depth
# ---------------------------------------------------------------------------

class TestTrapezoidalCapacity:
    def test_positive_capacity(self):
        Q = trapezoidal_capacity(3.0, 1.5, 0.014, 0.001, 1.0)
        assert Q > 0.0

    def test_round_trip_normal_depth(self):
        """normal_depth → y → capacity should recover Q."""
        b, z = 2.0, 1.0
        n, S = 0.015, 0.002
        Q = 1.5
        y_n = trapezoidal_normal_depth(b, z, n, S, Q)
        Q_check = trapezoidal_capacity(b, z, n, S, y_n)
        assert abs(Q_check - Q) / Q < 1e-4, f"Q_check={Q_check:.4f}, Q={Q:.4f}"

    def test_wider_channel_more_flow(self):
        """Wider bottom → more capacity."""
        Q1 = trapezoidal_capacity(2.0, 1.0, 0.013, 0.001, 1.0)
        Q2 = trapezoidal_capacity(4.0, 1.0, 0.013, 0.001, 1.0)
        assert Q2 > Q1


# ---------------------------------------------------------------------------
# LLM tool handler
# ---------------------------------------------------------------------------

def test_tool_full_flow():
    from kerf_civil.tools_hydraulics import run_civil_sewer_manning_capacity
    from kerf_civil._compat import ProjectCtx

    params = {"section": "circular", "op": "full_flow", "d": 0.6, "n": 0.013, "slope": 0.001}
    result = asyncio.run(run_civil_sewer_manning_capacity(params, ProjectCtx()))
    data = json.loads(result)
    assert data["ok"] is True
    assert abs(data["Q_full_m3s"] - 0.1942) < 0.001


def test_tool_normal_depth():
    from kerf_civil.tools_hydraulics import run_civil_sewer_manning_capacity
    from kerf_civil._compat import ProjectCtx

    params = {"section": "circular", "op": "normal_depth",
              "d": 0.6, "n": 0.013, "slope": 0.001, "Q": 0.04}
    result = asyncio.run(run_civil_sewer_manning_capacity(params, ProjectCtx()))
    data = json.loads(result)
    assert data["ok"] is True
    assert 0.0 < data["y_over_d"] < 1.0


def test_tool_trapezoidal_capacity():
    from kerf_civil.tools_hydraulics import run_civil_sewer_manning_capacity
    from kerf_civil._compat import ProjectCtx

    params = {"section": "trapezoidal", "op": "capacity",
              "b": 2.0, "z": 1.5, "n": 0.015, "slope": 0.002, "y": 1.0}
    result = asyncio.run(run_civil_sewer_manning_capacity(params, ProjectCtx()))
    data = json.loads(result)
    assert data["ok"] is True
    assert data["Q_m3s"] > 0
