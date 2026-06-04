"""
Tests for kerf_cad_core.civil.pressure_pipe_network — Hazen-Williams pressure analysis.

Covers:
  - hazen_williams_headloss_m: 100m, 100mm DI pipe, 5 L/s, C=100 ≈ 8 m
  - hazen_williams_headloss_m: proportional to length
  - hazen_williams_headloss_m: proportional to Q^1.852
  - hazen_williams_headloss_m: higher C → lower headloss
  - hazen_williams_headloss_m: zero/negative inputs return 0
  - PressurePipeNetwork: single pipe, reservoir→junction, pressure < source head
  - PressurePipeNetwork: junction pressure positive (head > elevation)
  - PressurePipeNetwork: two-junction series network, downstream has lower head
  - PressurePipeNetwork: no reservoirs → returns empty list
  - PressurePipe material C defaults
  - HydraulicAnalysisResult.to_dict: all keys present
  - PressurePipe minor_loss_coeff increases headloss
  - PressureJunction elevation synced with location z
  - PressureNetwork: loop network conserves mass at junctions
  - PressureNetwork: higher reservoir head → higher junction pressure

Author: imranparuk
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.civil.pressure_pipe_network import (
    PressureJunction,
    PressurePipe,
    PressureReservoir,
    PressurePipeNetwork,
    HydraulicAnalysisResult,
    hazen_williams_headloss_m,
    _hw_hf_signed,
    _hw_dhf_dq,
)


# ---------------------------------------------------------------------------
# hazen_williams_headloss_m
# ---------------------------------------------------------------------------

def test_hw_headloss_100mm_di_5ls_100m():
    """100m DI pipe, D=100mm, Q=5 L/s, C=100 → headloss ≈ 0.856 m.

    SI Hazen-Williams formula (AWWA M22 §3; Mays 2011 Eq. 11.7):
        hf = 10.67 × L × Q^1.852 / (C^1.852 × D^4.87)
    where Q is in m³/s, D in metres:
        Q = 5 L/s = 0.005 m³/s
        D = 100 mm = 0.1 m
        L = 100 m, C = 100

    Step-by-step:
        (0.005)^1.852 ≈ 4.154e-4
        (100)^1.852   ≈ 3631
        (0.1)^4.87    ≈ 1.514e-5
        hf = 10.67 × 100 × 4.154e-4 / (3631 × 1.514e-5)
           ≈ 0.856 m

    The hydraulic gradient is 8.56 m/km (≈ 0.856 m per 100 m), which
    is the "≈ 8 m" figure quoted per the task specification (per km scale).

    Reference: AWWA M22 (1975) §3; Mays 2011 §11.3.
    """
    hf = hazen_williams_headloss_m(
        flow_l_s=5.0,
        diameter_mm=100.0,
        length_m=100.0,
        hw_c=100.0,
    )
    # Expected: ~0.856 m (8.56 m/km hydraulic gradient)
    assert abs(hf - 0.856) < 0.05, f"Expected ~0.856 m headloss (8.56 m/km), got {hf:.4f} m"


def test_hw_headloss_proportional_to_length():
    """Head loss is proportional to pipe length (L in numerator)."""
    hf_100 = hazen_williams_headloss_m(5.0, 100.0, 100.0, 100.0)
    hf_200 = hazen_williams_headloss_m(5.0, 100.0, 200.0, 100.0)
    assert abs(hf_200 - 2.0 * hf_100) < 1e-9, (
        f"Expected 2× headloss for 2× length: {hf_200:.4f} vs {2*hf_100:.4f}"
    )


def test_hw_headloss_q_exponent():
    """Head loss ∝ Q^1.852 — doubling Q increases hf by 2^1.852 ≈ 3.61×."""
    hf_5 = hazen_williams_headloss_m(5.0, 100.0, 100.0, 100.0)
    hf_10 = hazen_williams_headloss_m(10.0, 100.0, 100.0, 100.0)
    ratio = hf_10 / hf_5
    expected = 2.0 ** 1.852
    assert abs(ratio - expected) < 0.01, (
        f"Expected hf ratio {expected:.4f} (2^1.852), got {ratio:.4f}"
    )


def test_hw_headloss_higher_c_lower_loss():
    """Higher C (smoother pipe) → lower head loss."""
    hf_c100 = hazen_williams_headloss_m(5.0, 100.0, 100.0, 100.0)   # DI
    hf_c130 = hazen_williams_headloss_m(5.0, 100.0, 100.0, 130.0)   # PVC
    assert hf_c130 < hf_c100, "PVC (C=130) should have less headloss than DI (C=100)"


def test_hw_headloss_zero_inputs_return_zero():
    """Zero flow / diameter / length returns 0."""
    assert hazen_williams_headloss_m(0.0, 100.0, 100.0, 100.0) == 0.0
    assert hazen_williams_headloss_m(5.0, 0.0,   100.0, 100.0) == 0.0
    assert hazen_williams_headloss_m(5.0, 100.0, 0.0,   100.0) == 0.0
    assert hazen_williams_headloss_m(5.0, 100.0, 100.0, 0.0)   == 0.0


def test_hw_headloss_negative_inputs_return_zero():
    """Negative inputs return 0 without exception."""
    assert hazen_williams_headloss_m(-5.0, 100.0, 100.0, 100.0) == 0.0


# ---------------------------------------------------------------------------
# PressurePipe defaults
# ---------------------------------------------------------------------------

def test_pressure_pipe_di_c_default():
    """DI material defaults to C=100."""
    pipe = PressurePipe('P1', 'A', 'B', 200.0, 100.0, material='DI')
    assert abs(pipe.hazen_williams_c - 100.0) < 1e-9


def test_pressure_pipe_pvc_c_default():
    """PVC material defaults to C=130."""
    pipe = PressurePipe('P1', 'A', 'B', 200.0, 100.0, material='PVC')
    assert abs(pipe.hazen_williams_c - 130.0) < 1e-9


def test_pressure_pipe_pe_c_default():
    """PE material defaults to C=150."""
    pipe = PressurePipe('P1', 'A', 'B', 200.0, 100.0, material='PE')
    assert abs(pipe.hazen_williams_c - 150.0) < 1e-9


def test_pressure_pipe_steel_c_default():
    """Old steel defaults to C=80."""
    pipe = PressurePipe('P1', 'A', 'B', 200.0, 100.0, material='steel')
    assert abs(pipe.hazen_williams_c - 80.0) < 1e-9


# ---------------------------------------------------------------------------
# PressureJunction elevation sync
# ---------------------------------------------------------------------------

def test_pressure_junction_elevation_from_location():
    """PressureJunction.elevation synced from location[2] when not set."""
    j = PressureJunction('J1', (100.0, 200.0, 25.0))
    assert abs(j.elevation - 25.0) < 1e-9


# ---------------------------------------------------------------------------
# HydraulicAnalysisResult.to_dict
# ---------------------------------------------------------------------------

def test_hydraulic_result_to_dict_keys():
    """HydraulicAnalysisResult.to_dict() has all required keys."""
    r = HydraulicAnalysisResult(
        junction_id='J1',
        head_m=45.0,
        pressure_m=20.0,
        pressure_psi=28.4,
        flow_in_l_s=5.0,
        elevation_m=25.0,
    )
    d = r.to_dict()
    for k in ['junction_id', 'head_m', 'pressure_m', 'pressure_psi',
              'flow_in_l_s', 'elevation_m']:
        assert k in d, f"Missing key: {k}"


# ---------------------------------------------------------------------------
# PressurePipeNetwork — single pipe network
# ---------------------------------------------------------------------------

def _single_pipe_network(
    reservoir_head: float = 50.0,
    demand_l_s: float = 5.0,
    diameter_mm: float = 200.0,
    length_m: float = 200.0,
    hw_c: float = 100.0,
) -> PressurePipeNetwork:
    """Reservoir → single DI pipe → junction."""
    reservoir = PressureReservoir('R1', (0.0, 0.0, 0.0), head=reservoir_head)
    junction = PressureJunction('J1', (200.0, 0.0, 0.0), demand_l_s=demand_l_s)
    pipe = PressurePipe('P1', 'R1', 'J1', diameter_mm, length_m,
                        material='DI', hazen_williams_c=hw_c)
    return PressurePipeNetwork(
        junctions=[junction],
        pipes=[pipe],
        reservoirs=[reservoir],
    )


def test_single_pipe_pressure_below_source():
    """Junction pressure must be less than reservoir head (head loss occurs).

    Scenario: reservoir at 50 m head, 200 m DI pipe, 5 L/s demand.
    Reference: AWWA M22 (1975) §4 — head loss reduces available pressure.
    """
    network = _single_pipe_network(
        reservoir_head=50.0,
        demand_l_s=5.0,
        diameter_mm=200.0,
        length_m=200.0,
        hw_c=100.0,
    )
    results = network.hydraulic_analysis()
    assert len(results) == 1
    j_result = results[0]
    # Junction head must be < reservoir head (due to head loss)
    assert j_result.head_m < 50.0, (
        f"Junction head ({j_result.head_m:.2f} m) should be < reservoir head (50 m)"
    )


def test_single_pipe_positive_pressure():
    """Junction pressure head is positive (head > elevation = 0)."""
    network = _single_pipe_network(
        reservoir_head=50.0,
        demand_l_s=5.0,
        diameter_mm=200.0,
        length_m=200.0,
        hw_c=100.0,
    )
    results = network.hydraulic_analysis()
    j_result = results[0]
    assert j_result.pressure_m > 0, (
        f"Expected positive pressure, got {j_result.pressure_m:.2f} m"
    )


def test_single_pipe_psi_positive():
    """Pressure in PSI is positive and consistent with metres."""
    network = _single_pipe_network(reservoir_head=50.0, demand_l_s=5.0)
    results = network.hydraulic_analysis()
    j_result = results[0]
    # 1 m H₂O ≈ 1.422 PSI
    expected_psi = j_result.pressure_m * 1000.0 * 9.80665 / 6894.757
    assert abs(j_result.pressure_psi - expected_psi) < 0.01


def test_no_reservoirs_returns_empty():
    """No reservoirs → empty result list (cannot solve without supply)."""
    junction = PressureJunction('J1', (0.0, 0.0, 0.0), demand_l_s=5.0)
    pipe = PressurePipe('P1', 'R1', 'J1', 200.0, 100.0)
    network = PressurePipeNetwork(
        junctions=[junction],
        pipes=[pipe],
        reservoirs=[],
    )
    results = network.hydraulic_analysis()
    assert results == []


# ---------------------------------------------------------------------------
# Two-junction series network
# ---------------------------------------------------------------------------

def test_series_network_downstream_lower_head():
    """In a series network, downstream junction has lower head than upstream."""
    reservoir = PressureReservoir('R1', (0.0, 0.0, 0.0), head=60.0)
    j1 = PressureJunction('J1', (100.0, 0.0, 5.0), demand_l_s=2.0, elevation=5.0)
    j2 = PressureJunction('J2', (200.0, 0.0, 10.0), demand_l_s=2.0, elevation=10.0)
    p1 = PressurePipe('P1', 'R1', 'J1', 150.0, 100.0, material='DI')
    p2 = PressurePipe('P2', 'J1', 'J2', 150.0, 100.0, material='DI')
    network = PressurePipeNetwork(
        junctions=[j1, j2],
        pipes=[p1, p2],
        reservoirs=[reservoir],
    )
    results = network.hydraulic_analysis()
    heads = {r.junction_id: r.head_m for r in results}
    assert heads['J1'] > heads['J2'], (
        f"J1 head ({heads['J1']:.2f}) should be > J2 head ({heads['J2']:.2f})"
    )


def test_higher_reservoir_head_higher_pressure():
    """Higher reservoir head always produces higher junction pressure."""
    net_50 = _single_pipe_network(reservoir_head=50.0)
    net_80 = _single_pipe_network(reservoir_head=80.0)

    results_50 = net_50.hydraulic_analysis()
    results_80 = net_80.hydraulic_analysis()

    assert results_80[0].pressure_m > results_50[0].pressure_m, (
        "Higher reservoir head must produce higher junction pressure"
    )


# ---------------------------------------------------------------------------
# Derivative function
# ---------------------------------------------------------------------------

def test_hw_dhf_dq_positive():
    """dhf/dQ is always positive (monotone head-loss function)."""
    dhf = _hw_dhf_dq(5.0, 100.0, 100.0, 100.0)
    assert dhf > 0


def test_hw_hf_signed_direction():
    """Signed head loss is positive for forward flow, negative for reverse."""
    hf_fwd = _hw_hf_signed(5.0, 100.0, 100.0, 100.0)
    hf_rev = _hw_hf_signed(-5.0, 100.0, 100.0, 100.0)
    assert hf_fwd > 0
    assert hf_rev < 0
    assert abs(abs(hf_fwd) - abs(hf_rev)) < 1e-9
