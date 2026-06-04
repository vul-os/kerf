"""
Test suite for kerf_fem.contact.penalty — penalty-method contact.

Coverage
--------
1.  Zero gap → zero contact force
2.  Open gap (slave above master) → zero force
3.  Penetration 1mm, k=1e9 N/m → 1MN normal force
4.  Normal force direction opposes penetration (outward)
5.  Coulomb friction: |F_t| ≤ μ·|F_n|
6.  Frictionless: tangential force is zero
7.  Larger penetration → larger contact force (linearity)
8.  Multiple slave nodes: only penetrating ones get force
9.  Contact force magnitude scales with penalty stiffness
10. contact_gap() returns correct positive/negative values
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_fem.contact.penalty import (
    compute_contact_force_penalty,
    contact_gap,
    ContactPair,
)


# ---------------------------------------------------------------------------
# Fixture: horizontal master surface at y=0
# ---------------------------------------------------------------------------

MASTER = np.array([[0.0, 0.0], [1.0, 0.0]])   # flat surface along x-axis, y=0
K = 1e9   # N/m


def test_zero_gap_zero_force():
    """Slave node exactly on master surface → zero contact force."""
    slave = np.array([[0.5, 0.0]])  # on the surface
    fn, ft = compute_contact_force_penalty(slave, MASTER, K)
    assert np.allclose(fn, 0.0, atol=1e-6)
    assert np.allclose(ft, 0.0, atol=1e-6)


def test_open_gap_zero_force():
    """Slave node above master surface → no contact force."""
    slave = np.array([[0.5, 0.01]])  # 10mm above
    fn, ft = compute_contact_force_penalty(slave, MASTER, K)
    assert np.allclose(fn, 0.0, atol=1e-10)
    assert np.allclose(ft, 0.0, atol=1e-10)


def test_penetration_1mm_gives_1MN():
    """1 mm penetration with k=1e9 N/m → 1 MN normal force."""
    penetration_m = 1e-3  # 1 mm
    slave = np.array([[0.5, -penetration_m]])  # 1mm below y=0
    fn, ft = compute_contact_force_penalty(slave, MASTER, K)
    force_magnitude = float(np.linalg.norm(fn[0]))
    expected = K * penetration_m  # 1e9 × 1e-3 = 1e6 N = 1 MN
    assert abs(force_magnitude - expected) / expected < 0.01, \
        f"Expected {expected:.3e} N, got {force_magnitude:.3e} N"


def test_normal_force_direction_outward():
    """Normal contact force must push slave node out of master surface."""
    slave = np.array([[0.5, -0.001]])  # below y=0
    fn, _ = compute_contact_force_penalty(slave, MASTER, K)
    # For master surface at y=0 (outward normal points +y), force must be +y
    assert fn[0, 1] > 0, f"Force y-component should be positive, got {fn[0,1]:.3e}"


def test_coulomb_friction_bounded():
    """Friction force must satisfy |F_t| ≤ μ·|F_n|."""
    penetration = 1e-3
    mu = 0.3
    slave = np.array([[0.5, -penetration]])
    fn, ft = compute_contact_force_penalty(slave, MASTER, K, friction_coefficient=mu)
    fn_mag = float(np.linalg.norm(fn[0]))
    ft_mag = float(np.linalg.norm(ft[0]))
    assert ft_mag <= mu * fn_mag * (1 + 1e-9), \
        f"Coulomb violated: |Ft|={ft_mag:.3e} > μ|Fn|={mu*fn_mag:.3e}"


def test_frictionless_zero_tangential():
    """mu=0 → no tangential force."""
    slave = np.array([[0.5, -0.001]])
    fn, ft = compute_contact_force_penalty(slave, MASTER, K, friction_coefficient=0.0)
    assert np.allclose(ft, 0.0, atol=1e-12)


def test_larger_penetration_larger_force():
    """Penalty method is linear: deeper penetration → larger force."""
    slave1 = np.array([[0.5, -0.001]])
    slave2 = np.array([[0.5, -0.002]])
    fn1, _ = compute_contact_force_penalty(slave1, MASTER, K)
    fn2, _ = compute_contact_force_penalty(slave2, MASTER, K)
    assert np.linalg.norm(fn2[0]) > np.linalg.norm(fn1[0])


def test_multiple_slaves_only_penetrating_get_force():
    """Only nodes with gap < 0 should get contact force."""
    slaves = np.array([
        [0.5,  0.005],   # above master: no contact
        [0.5, -0.001],   # below master: contact
        [0.5,  0.0],     # on surface: no contact
    ])
    fn, ft = compute_contact_force_penalty(slaves, MASTER, K)
    assert np.allclose(fn[0], 0.0, atol=1e-10), "Above-surface node should have zero force"
    assert np.allclose(fn[2], 0.0, atol=1e-10), "On-surface node should have zero force"
    assert np.linalg.norm(fn[1]) > 0, "Penetrating node must have nonzero force"


def test_force_scales_with_stiffness():
    """Contact force is proportional to penalty stiffness."""
    slave = np.array([[0.5, -0.001]])
    fn_k1, _ = compute_contact_force_penalty(slave, MASTER, 1e6)
    fn_k2, _ = compute_contact_force_penalty(slave, MASTER, 2e6)
    ratio = np.linalg.norm(fn_k2[0]) / np.linalg.norm(fn_k1[0])
    assert abs(ratio - 2.0) < 1e-6


def test_contact_gap_positive_for_open():
    """contact_gap > 0 when slave is above master surface."""
    slave = np.array([[0.5, 0.01]])
    gaps = contact_gap(slave, MASTER)
    assert gaps[0] > 0


def test_contact_gap_negative_for_penetration():
    """contact_gap < 0 when slave is below master surface."""
    slave = np.array([[0.5, -0.01]])
    gaps = contact_gap(slave, MASTER)
    assert gaps[0] < 0
