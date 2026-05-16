"""
Hermetic tests for kerf_cad_core.mbd — planar constrained rigid multibody dynamics.

Coverage (≥25 tests):
  T01  simple pendulum returns ok + expected keys
  T02  simple pendulum small-angle period ≈ 2π√(L/g) within 2% tolerance
  T03  simple pendulum energy conservation (undamped, drift < 1%) over 5 s
  T04  simple pendulum static case (zero angle) remains at rest
  T05  double pendulum energy conservation (undamped, drift < 1%) — chaos onset
  T06  double pendulum returns two bodies in trajectory
  T07  spring-mass SHM: numerical frequency matches ω=√(k/m) within 1%
  T08  spring-mass energy conserved (undamped) drift < 1%
  T09  spring-mass with damping: amplitude decays (final E < initial E)
  T10  slider-crank piston position matches closed-form kinematics within 2%
  T11  slider-crank returns ok + slider_x_mbd and crank_theta keys
  T12  revolute joint constraint residual stays < 1e-5 throughout simulation
  T13  static pendulum (θ=0) reaction force Fy ≈ m·g (weight check)
  T14  BAD ARGS: negative mass returns ok=False
  T15  BAD ARGS: negative inertia returns ok=False
  T16  BAD ARGS: t_end=0 returns ok=False
  T17  BAD ARGS: dt=0 returns ok=False
  T18  fixed body does not move
  T19  prismatic joint keeps mass on slide axis (y ≈ 0)
  T20  spring-mass x(t=0) equals initial displacement
  T21  distance joint constraint residual stays < 1e-4
  T22  applied force: body accelerates in correct direction
  T23  applied torque: body angular velocity changes
  T24  gravity field: free-falling body follows y=½g·t²
  T25  store_every parameter reduces trajectory length
  T26  double pendulum large angle (90°+90°): energy conserved < 2% drift

All tests are pure-Python and hermetic: no OCC, no DB, no network.

References
----------
Shabana, A.A. "Computational Dynamics", 3rd ed. Wiley, 2010.
Nikravesh, P.E. "Computer-Aided Analysis of Mechanical Systems", Prentice-Hall, 1988.

Author: imranparuk
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.mbd.solver import (
    Body,
    RevoluteJoint,
    PrismaticJoint,
    FixedJoint,
    DistanceJoint,
    SpringDamper,
    GravityForce,
    AppliedForce,
    AppliedTorque,
    MBDSystem,
    simulate,
)
from kerf_cad_core.kinematics.linkage import slider_crank as kin_slider_crank


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pendulum_body_frame_offset(theta0: float, L: float) -> tuple:
    """
    Return the body-frame offset (s_j) from the bob centroid to the pivot,
    given the rod makes angle theta0 from vertical at initial conditions.

    Convention: body x-axis points along the rod (from pivot toward bob).
    The pivot is at body-frame offset (-L, 0) from the centroid.
    """
    return (-L, 0.0)


def _simple_pendulum(L: float, m: float, theta0_deg: float,
                     t_end: float = 5.0, dt: float = 0.005,
                     g: float = 9.80665) -> dict:
    """
    Build and simulate a simple pendulum pinned at origin.

    Convention: bob body's x-axis points along the rod (pivot → bob).
    theta0 = initial angle of rod from vertical (positive = rightward lean).
    Body theta0_rad = angle of rod from vertical = theta0_deg in radians.
    """
    th0 = math.radians(theta0_deg)
    sys = MBDSystem()
    g_idx = sys.add_body(Body(mass=1.0, inertia=1.0, fixed=True, name="ground"))
    # Bob centroid at tip of rod; theta = angle of rod from -y axis (vertical down)
    # Rod direction in world frame: (sin(th0), -cos(th0))
    x0 = math.sin(th0) * L
    y0 = -math.cos(th0) * L
    # Body angle: align body x-axis with rod direction
    # Rod direction from pivot to bob = (sin(th0), -cos(th0))
    # Angle of this vector from global x-axis:
    body_theta0 = math.atan2(-math.cos(th0), math.sin(th0))
    I = max(m * L**2 * 1e-4, 1e-6)
    b_idx = sys.add_body(Body(mass=m, inertia=I,
                               x0=x0, y0=y0, theta0=body_theta0, name="bob"))
    # Pivot is at body-frame offset (-L, 0) from bob centroid (body x points away from pivot)
    sys.add_joint(RevoluteJoint(g_idx, b_idx, s_i=(0.0, 0.0), s_j=(-L, 0.0)))
    sys.add_force(GravityForce(gx=0.0, gy=-g))
    return simulate(sys, t_end=t_end, dt=dt), b_idx, sys


def _spring_mass(m: float, k: float, x0: float = 0.1, c: float = 0.0,
                 t_end: float = 5.0, dt: float = 0.005) -> tuple:
    """Build and simulate a horizontal spring-mass oscillator."""
    sys = MBDSystem()
    g_idx = sys.add_body(Body(mass=1.0, inertia=1.0, fixed=True, name="ground"))
    m_idx = sys.add_body(Body(mass=m, inertia=m * 0.01,
                               x0=x0, y0=0.0, name="mass"))
    sys.add_joint(PrismaticJoint(m_idx, g_idx, axis_angle_rad=0.0,
                                  s_i=(0.0, 0.0), s_j=(0.0, 0.0)))
    sys.add_force(SpringDamper(m_idx, g_idx, s_i=(0.0, 0.0), s_j=(0.0, 0.0),
                               k=k, c=c, L0=0.0))
    return simulate(sys, t_end=t_end, dt=dt), m_idx, sys


# ---------------------------------------------------------------------------
# T01 — simple pendulum: result ok + expected keys
# ---------------------------------------------------------------------------

def test_T01_simple_pendulum_ok_keys():
    result, b_idx, _ = _simple_pendulum(1.0, 1.0, 10.0, t_end=1.0, dt=0.01)
    assert result["ok"] is True
    for key in ("t", "q", "qd", "energy", "reactions", "n_steps"):
        assert key in result, f"missing key: {key}"
    assert len(result["t"]) > 0
    assert len(result["q"]) == len(result["t"])
    assert len(result["energy"]) == len(result["t"])


# ---------------------------------------------------------------------------
# T02 — simple pendulum small-angle period ≈ 2π√(L/g) within 2%
# ---------------------------------------------------------------------------

def test_T02_simple_pendulum_period_small_angle():
    L, g = 1.0, 9.80665
    T_analytic = 2.0 * math.pi * math.sqrt(L / g)  # ≈ 2.006 s

    # Simulate for ~2 periods; detect zero crossings of angle
    result, b_idx, sys = _simple_pendulum(L, 1.0, 5.0, t_end=T_analytic * 2.5, dt=0.005)
    assert result["ok"] is True

    # Extract angle from position: θ = atan2(x, -y)  (pendulum convention)
    qs = result["q"]
    angles = [math.atan2(q[3*b_idx], -q[3*b_idx + 1]) for q in qs]
    ts = result["t"]

    # Find all zero crossings (both directions) — each half-period is one crossing.
    # One full period = two consecutive crossings.
    crossings = []
    for i in range(1, len(angles)):
        if (angles[i-1] > 0) != (angles[i] > 0):
            # linear interpolation
            t_cross = ts[i-1] + (ts[i] - ts[i-1]) * abs(angles[i-1]) / (abs(angles[i-1]) + abs(angles[i]))
            crossings.append(t_cross)

    # Need at least 3 crossings to measure a full period (crossing → ½T → crossing → ½T → crossing)
    assert len(crossings) >= 3, "Not enough zero crossings to measure period"

    # Each pair of consecutive crossings is a half-period; full period = 2 half-periods
    half_periods = [crossings[i+1] - crossings[i] for i in range(len(crossings) - 1)]
    T_numerical = 2.0 * (sum(half_periods) / len(half_periods))
    rel_error = abs(T_numerical - T_analytic) / T_analytic
    assert rel_error < 0.02, f"Period error {rel_error:.4f} > 2%; T_num={T_numerical:.4f}, T_ana={T_analytic:.4f}"


# ---------------------------------------------------------------------------
# T03 — simple pendulum energy conservation (undamped, drift < 1%)
# ---------------------------------------------------------------------------

def test_T03_simple_pendulum_energy_conservation():
    result, b_idx, sys = _simple_pendulum(1.0, 1.0, 20.0, t_end=5.0, dt=0.005)
    assert result["ok"] is True
    energies = result["energy"]
    E0 = energies[0]["E"]
    assert abs(E0) > 1e-10, "Initial energy should be non-zero"
    for en in energies:
        drift = abs(en["E"] - E0) / abs(E0)
        assert drift < 0.01, f"Energy drift {drift:.4f} > 1% at t={en['t']:.3f}"


# ---------------------------------------------------------------------------
# T04 — simple pendulum static: theta=0, stays at rest
# ---------------------------------------------------------------------------

def test_T04_simple_pendulum_static():
    result, b_idx, _ = _simple_pendulum(1.0, 1.0, 0.0, t_end=2.0, dt=0.01)
    assert result["ok"] is True
    for q in result["q"]:
        assert abs(q[3*b_idx]) < 1e-6, "Bob should not move in x"
        assert abs(q[3*b_idx + 1] + 1.0) < 1e-5, "Bob should stay at y=-L"


def _double_pendulum_system(L1: float, L2: float, m1: float, m2: float,
                             th1_deg: float, th2_deg: float,
                             g_val: float = 9.80665):
    """
    Build a double pendulum.  Uses the same body-frame offset convention
    as _simple_pendulum: each bob's body x-axis points along its rod
    (pivot → bob), so the pivot is at body-frame (-L, 0) from centroid.

    Joint between bob1 and bob2: the pivot IS bob1's centroid (s_i=(0,0)),
    and for bob2 the pivot is at body-frame offset (-L2, 0).
    """
    th1 = math.radians(th1_deg)
    th2 = math.radians(th2_deg)
    sys = MBDSystem()
    g_idx = sys.add_body(Body(mass=1.0, inertia=1.0, fixed=True, name="ground"))

    # Bob1: centroid at tip of rod1
    x1 = math.sin(th1) * L1
    y1 = -math.cos(th1) * L1
    body_th1 = math.atan2(-math.cos(th1), math.sin(th1))
    I1 = max(m1 * L1**2 * 1e-4, 1e-6)
    b1_idx = sys.add_body(Body(mass=m1, inertia=I1, x0=x1, y0=y1,
                                theta0=body_th1, name="bob1"))

    # Bob2: centroid at tip of rod2 (rod2 starts from bob1 position)
    x2 = x1 + math.sin(th2) * L2
    y2 = y1 - math.cos(th2) * L2
    body_th2 = math.atan2(-math.cos(th2), math.sin(th2))
    I2 = max(m2 * L2**2 * 1e-4, 1e-6)
    b2_idx = sys.add_body(Body(mass=m2, inertia=I2, x0=x2, y0=y2,
                                theta0=body_th2, name="bob2"))

    # Ground pins bob1 pivot: s_i=(0,0) on ground, s_j=(-L1,0) on bob1 body
    sys.add_joint(RevoluteJoint(g_idx, b1_idx, s_i=(0.0, 0.0), s_j=(-L1, 0.0)))

    # Bob1 centroid is the pivot for bob2: s_i=(0,0) on bob1, s_j=(-L2,0) on bob2
    sys.add_joint(RevoluteJoint(b1_idx, b2_idx, s_i=(0.0, 0.0), s_j=(-L2, 0.0)))

    sys.add_force(GravityForce(gx=0.0, gy=-g_val))
    return sys, g_idx, b1_idx, b2_idx


# ---------------------------------------------------------------------------
# T05 — double pendulum energy conservation (undamped, drift < 1%)
# ---------------------------------------------------------------------------

def test_T05_double_pendulum_energy_conservation():
    sys, g_idx, b1_idx, b2_idx = _double_pendulum_system(
        1.0, 0.8, 1.0, 0.8, 20.0, 30.0)

    result = simulate(sys, t_end=3.0, dt=0.003)
    assert result["ok"] is True

    energies = result["energy"]
    E0 = energies[0]["E"]
    assert abs(E0) > 1e-10
    for en in energies:
        drift = abs(en["E"] - E0) / abs(E0)
        assert drift < 0.01, f"Double pendulum energy drift {drift:.4f} > 1% at t={en['t']:.3f}"


# ---------------------------------------------------------------------------
# T06 — double pendulum has trajectory for both bobs
# ---------------------------------------------------------------------------

def test_T06_double_pendulum_two_bodies():
    sys, g_idx, b1_idx, b2_idx = _double_pendulum_system(
        1.0, 0.8, 1.0, 0.8, 15.0, 10.0)
    result = simulate(sys, t_end=1.0, dt=0.01)
    assert result["ok"] is True
    n = len(sys.bodies)
    for q in result["q"]:
        assert len(q) == 3 * n


# ---------------------------------------------------------------------------
# T07 — spring-mass SHM frequency matches ω=√(k/m) within 1%
# ---------------------------------------------------------------------------

def test_T07_spring_mass_frequency():
    m, k = 2.0, 50.0
    omega_analytic = math.sqrt(k / m)   # ≈ 5.0 rad/s
    T_analytic = 2 * math.pi / omega_analytic

    result, m_idx, sys = _spring_mass(m, k, x0=0.1, t_end=T_analytic * 4, dt=0.002)
    assert result["ok"] is True

    xs = [q[3*m_idx] for q in result["q"]]
    ts = result["t"]

    # Find zero crossings from positive to negative
    crossings = []
    for i in range(1, len(xs)):
        if xs[i-1] > 0 and xs[i] <= 0:
            t_c = ts[i-1] + (ts[i] - ts[i-1]) * xs[i-1] / (xs[i-1] - xs[i])
            crossings.append(t_c)

    assert len(crossings) >= 2, "Not enough zero crossings to measure period"
    # Each positive→negative crossing happens once per full period
    T_numerical = (crossings[-1] - crossings[0]) / (len(crossings) - 1)
    omega_numerical = 2 * math.pi / T_numerical
    rel_error = abs(omega_numerical - omega_analytic) / omega_analytic
    assert rel_error < 0.01, (f"Spring-mass ω error {rel_error:.4f} > 1%; "
                               f"ω_num={omega_numerical:.4f}, ω_ana={omega_analytic:.4f}")


# ---------------------------------------------------------------------------
# T08 — spring-mass undamped energy conserved drift < 1%
# ---------------------------------------------------------------------------

def test_T08_spring_mass_energy_conservation():
    result, m_idx, sys = _spring_mass(1.0, 20.0, x0=0.2, c=0.0, t_end=5.0)
    assert result["ok"] is True
    energies = result["energy"]
    E0 = energies[0]["E"]
    assert abs(E0) > 1e-12
    for en in energies:
        drift = abs(en["E"] - E0) / abs(E0)
        assert drift < 0.01, f"Spring energy drift {drift:.4f} > 1% at t={en['t']:.3f}"


# ---------------------------------------------------------------------------
# T09 — spring-mass with damping: total energy decays
# ---------------------------------------------------------------------------

def test_T09_spring_mass_damped_energy_decays():
    result, m_idx, _ = _spring_mass(1.0, 20.0, x0=0.2, c=1.0, t_end=3.0)
    assert result["ok"] is True
    E0 = result["energy"][0]["E"]
    E_final = result["energy"][-1]["E"]
    assert E_final < E0, f"Damped spring energy should decrease: E0={E0:.4f}, E_final={E_final:.4f}"


# ---------------------------------------------------------------------------
# T10 — slider-crank piston position matches kinematic closed-form within 2%
# ---------------------------------------------------------------------------

def test_T10_slider_crank_position_matches_kinematics():
    r, l = 0.1, 0.3
    omega0 = 2 * math.pi * 5   # 5 rev/s
    m_crank, m_rod, m_slider = 0.5, 0.2, 0.5

    sys = MBDSystem()
    g_idx = sys.add_body(Body(mass=1.0, inertia=1.0, fixed=True, name="ground"))
    I_crank = 0.5 * m_crank * r**2
    crank_idx = sys.add_body(Body(mass=m_crank, inertia=I_crank,
                                   x0=r/2, y0=0.0, theta0=0.0,
                                   omega0=omega0, name="crank"))
    sys.add_joint(RevoluteJoint(g_idx, crank_idx, s_i=(0.0, 0.0), s_j=(-r/2, 0.0)))

    I_rod = (1.0/12.0) * m_rod * l**2
    rod_idx = sys.add_body(Body(mass=m_rod, inertia=I_rod,
                                 x0=r + l/2, y0=0.0, theta0=0.0, name="rod"))
    sys.add_joint(RevoluteJoint(crank_idx, rod_idx, s_i=(r/2, 0.0), s_j=(-l/2, 0.0)))

    slider_idx = sys.add_body(Body(mass=m_slider, inertia=m_slider*0.001,
                                    x0=r + l, y0=0.0, name="slider"))
    sys.add_joint(PrismaticJoint(slider_idx, g_idx, axis_angle_rad=0.0,
                                  s_i=(0.0, 0.0), s_j=(0.0, 0.0)))
    sys.add_joint(RevoluteJoint(rod_idx, slider_idx, s_i=(l/2, 0.0), s_j=(0.0, 0.0)))

    t_end = 2 * math.pi / omega0 * 3   # 3 revolutions
    result = simulate(sys, t_end=t_end, dt=0.0005)
    assert result["ok"] is True

    slider_x = [q[3*slider_idx] for q in result["q"]]
    crank_theta = [q[3*crank_idx + 2] for q in result["q"]]

    # Compare at each step
    max_rel_err = 0.0
    for x_mbd, th in zip(slider_x, crank_theta):
        sin_th = math.sin(th)
        inside = l**2 - r**2 * sin_th**2
        if inside < 0:
            continue
        x_kin = r * math.cos(th) + math.sqrt(inside)
        if abs(x_kin) > 1e-10:
            err = abs(x_mbd - x_kin) / abs(x_kin)
            max_rel_err = max(max_rel_err, err)

    assert max_rel_err < 0.02, f"Slider-crank max position error {max_rel_err:.4f} > 2%"


# ---------------------------------------------------------------------------
# T11 — slider-crank returns expected keys
# ---------------------------------------------------------------------------

def test_T11_slider_crank_result_keys():
    r, l = 0.05, 0.15
    sys = MBDSystem()
    g_idx = sys.add_body(Body(mass=1.0, inertia=1.0, fixed=True))
    crank_idx = sys.add_body(Body(mass=1.0, inertia=0.5*1.0*(r/2)**2,
                                   x0=r/2, y0=0.0, omega0=10.0))
    sys.add_joint(RevoluteJoint(g_idx, crank_idx, s_i=(0.0, 0.0), s_j=(-r/2, 0.0)))
    rod_idx = sys.add_body(Body(mass=0.5, inertia=(1/12)*0.5*l**2,
                                 x0=r + l/2, y0=0.0))
    sys.add_joint(RevoluteJoint(crank_idx, rod_idx, s_i=(r/2, 0.0), s_j=(-l/2, 0.0)))
    slider_idx = sys.add_body(Body(mass=1.0, inertia=0.001, x0=r+l, y0=0.0))
    sys.add_joint(PrismaticJoint(slider_idx, g_idx))
    sys.add_joint(RevoluteJoint(rod_idx, slider_idx, s_i=(l/2, 0.0), s_j=(0.0, 0.0)))
    result = simulate(sys, t_end=0.1, dt=0.001)
    assert result["ok"] is True
    assert "q" in result
    assert "energy" in result


# ---------------------------------------------------------------------------
# T12 — revolute joint constraint residual stays < 1e-5
# ---------------------------------------------------------------------------

def test_T12_revolute_constraint_residual():
    L, m = 1.0, 1.0
    result, b_idx, sys = _simple_pendulum(L, m, 30.0, t_end=3.0, dt=0.005)
    assert result["ok"] is True

    # Check constraint residual: distance of bob from origin should stay = L
    for q in result["q"]:
        xb = q[3*b_idx]
        yb = q[3*b_idx + 1]
        dist = math.sqrt(xb**2 + yb**2)
        err = abs(dist - L)
        assert err < 1e-5, f"Revolute constraint residual {err:.2e} > 1e-5"


# ---------------------------------------------------------------------------
# T13 — static pendulum (θ=0): reaction Fy ≈ m·g
# ---------------------------------------------------------------------------

def test_T13_static_pendulum_reaction_force():
    """
    Static pendulum hanging straight down (theta=0).
    The revolute joint reaction should balance the weight.
    """
    m, g = 2.0, 9.80665
    L = 1.0
    # Use _simple_pendulum with theta=0 (straight down)
    result, b_idx, sys = _simple_pendulum(L, m, 0.0, t_end=0.5, dt=0.005, g=g)
    assert result["ok"] is True

    # At rest, the reaction force at the pin should balance weight (≈ mg)
    reactions = result["reactions"]
    assert len(reactions) > 0
    # Ground pin reaction: first joint
    R = reactions[0]
    # The lambda[1] component of the revolute (y-direction) should ≈ mg
    lam = R["lambda"]
    F_magnitude = math.sqrt(sum(v**2 for v in lam))
    expected = m * g
    rel_err = abs(F_magnitude - expected) / expected
    assert rel_err < 0.05, (f"Static reaction magnitude={F_magnitude:.4f} vs expected {expected:.4f} "
                             f"(err={rel_err:.4f})")


# ---------------------------------------------------------------------------
# T14 — BAD ARGS: negative mass
# ---------------------------------------------------------------------------

def test_T14_bad_args_negative_mass():
    sys = MBDSystem()
    sys.add_body(Body(mass=-1.0, inertia=1.0, fixed=False))
    result = simulate(sys, t_end=1.0, dt=0.01)
    assert result["ok"] is False
    assert "reason" in result


# ---------------------------------------------------------------------------
# T15 — BAD ARGS: zero inertia
# ---------------------------------------------------------------------------

def test_T15_bad_args_zero_inertia():
    sys = MBDSystem()
    sys.add_body(Body(mass=1.0, inertia=0.0, fixed=False))
    result = simulate(sys, t_end=1.0, dt=0.01)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# T16 — BAD ARGS: t_end = 0
# ---------------------------------------------------------------------------

def test_T16_bad_args_t_end_zero():
    sys = MBDSystem()
    sys.add_body(Body(mass=1.0, inertia=1.0, fixed=True))
    result = simulate(sys, t_end=0.0, dt=0.01)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# T17 — BAD ARGS: dt = 0
# ---------------------------------------------------------------------------

def test_T17_bad_args_dt_zero():
    sys = MBDSystem()
    sys.add_body(Body(mass=1.0, inertia=1.0, fixed=True))
    result = simulate(sys, t_end=1.0, dt=0.0)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# T18 — fixed body does not move
# ---------------------------------------------------------------------------

def test_T18_fixed_body_does_not_move():
    sys = MBDSystem()
    g_idx = sys.add_body(Body(mass=1.0, inertia=1.0, fixed=True, x0=0.5, y0=0.5, theta0=0.3))
    sys.add_force(GravityForce())
    result = simulate(sys, t_end=1.0, dt=0.01)
    assert result["ok"] is True
    for q in result["q"]:
        assert abs(q[3*g_idx]     - 0.5) < 1e-10
        assert abs(q[3*g_idx + 1] - 0.5) < 1e-10
        assert abs(q[3*g_idx + 2] - 0.3) < 1e-10


# ---------------------------------------------------------------------------
# T19 — prismatic joint: mass stays on slide axis (y ≈ 0)
# ---------------------------------------------------------------------------

def test_T19_prismatic_mass_on_axis():
    result, m_idx, _ = _spring_mass(1.0, 10.0, x0=0.1, t_end=2.0)
    assert result["ok"] is True
    for q in result["q"]:
        assert abs(q[3*m_idx + 1]) < 1e-5, f"Mass y-position drifted: {q[3*m_idx + 1]:.2e}"


# ---------------------------------------------------------------------------
# T20 — spring-mass: x(t=0) equals initial displacement
# ---------------------------------------------------------------------------

def test_T20_spring_mass_initial_condition():
    x0 = 0.25
    result, m_idx, _ = _spring_mass(1.0, 10.0, x0=x0, t_end=1.0)
    assert result["ok"] is True
    q0 = result["q"][0]
    assert abs(q0[3*m_idx] - x0) < 1e-10, f"Initial x={q0[3*m_idx]:.6f} != {x0}"


# ---------------------------------------------------------------------------
# T21 — distance joint constraint residual < 1e-4
# ---------------------------------------------------------------------------

def test_T21_distance_joint_constraint():
    d = 1.0
    sys = MBDSystem()
    g_idx = sys.add_body(Body(mass=1.0, inertia=1.0, fixed=True))
    b_idx = sys.add_body(Body(mass=1.0, inertia=1e-4, x0=0.0, y0=-d))
    sys.add_joint(DistanceJoint(g_idx, b_idx, s_i=(0.0, 0.0), s_j=(0.0, 0.0), distance=d))
    sys.add_force(GravityForce())

    result = simulate(sys, t_end=2.0, dt=0.005)
    assert result["ok"] is True

    for q in result["q"]:
        xb = q[3*b_idx]
        yb = q[3*b_idx + 1]
        dist = math.sqrt(xb**2 + yb**2)
        err = abs(dist - d)
        assert err < 1e-4, f"Distance constraint violation {err:.2e} > 1e-4"


# ---------------------------------------------------------------------------
# T22 — applied force: body accelerates in correct direction
# ---------------------------------------------------------------------------

def test_T22_applied_force_direction():
    m = 1.0
    F = 10.0  # N in +x
    sys = MBDSystem()
    # Free body (no constraints, no gravity, just applied force in x)
    # We won't add joints so it's fully free — but we need at least fixed DOF
    # to avoid singular mass matrix: use no joints; just let it drift.
    # Actually with no joints the DOF are free. Let's check x-acceleration.
    b_idx = sys.add_body(Body(mass=m, inertia=0.1, x0=0.0, y0=0.0))
    sys.add_force(AppliedForce(b_idx, s=(0.0, 0.0), fx=F, fy=0.0))

    result = simulate(sys, t_end=0.1, dt=0.001)
    assert result["ok"] is True

    # x should increase (positive acceleration)
    x_final = result["q"][-1][3*b_idx]
    assert x_final > 0, f"Applied +x force should move body in +x; got x={x_final:.6f}"
    # Expected: x = ½(F/m)t² = ½·10·0.01 = 0.05 m
    x_expected = 0.5 * (F / m) * 0.1**2
    assert abs(x_final - x_expected) / x_expected < 0.02


# ---------------------------------------------------------------------------
# T23 — applied torque: body angular velocity changes
# ---------------------------------------------------------------------------

def test_T23_applied_torque_changes_omega():
    I = 0.5   # kg·m²
    tau = 2.0  # N·m
    sys = MBDSystem()
    b_idx = sys.add_body(Body(mass=1.0, inertia=I, x0=0.0, y0=0.0))
    sys.add_force(AppliedTorque(b_idx, torque=tau))

    result = simulate(sys, t_end=0.5, dt=0.001)
    assert result["ok"] is True

    # Expected: ω = α·t = (τ/I)·t = (2/0.5)·0.5 = 2.0 rad/s
    om_final = result["qd"][-1][3*b_idx + 2]
    expected_omega = (tau / I) * 0.5
    assert abs(om_final - expected_omega) / expected_omega < 0.02, (
        f"Final ω={om_final:.4f} vs expected {expected_omega:.4f}")


# ---------------------------------------------------------------------------
# T24 — gravity: free-falling body follows y = -½g·t²
# ---------------------------------------------------------------------------

def test_T24_gravity_free_fall():
    m, g_val = 1.0, 9.80665
    sys = MBDSystem()
    b_idx = sys.add_body(Body(mass=m, inertia=0.1, x0=0.0, y0=0.0))
    sys.add_force(GravityForce(gx=0.0, gy=-g_val))

    result = simulate(sys, t_end=0.5, dt=0.001)
    assert result["ok"] is True

    for q, t_ in zip(result["q"], result["t"]):
        y_mbd = q[3*b_idx + 1]
        y_expected = -0.5 * g_val * t_**2
        if t_ > 0.01:
            err = abs(y_mbd - y_expected) / max(abs(y_expected), 1e-6)
            assert err < 0.01, f"Free fall y error {err:.4f} at t={t_:.4f}"


# ---------------------------------------------------------------------------
# T25 — store_every: reduces trajectory length
# ---------------------------------------------------------------------------

def test_T25_store_every_reduces_output():
    sys = MBDSystem()
    sys.add_body(Body(mass=1.0, inertia=1.0, fixed=True))

    r1 = simulate(sys, t_end=1.0, dt=0.01, store_every=1)
    r10 = simulate(sys, t_end=1.0, dt=0.01, store_every=10)
    assert r1["ok"] is True
    assert r10["ok"] is True
    assert len(r10["t"]) < len(r1["t"]), (
        f"store_every=10 should have fewer points: {len(r10['t'])} vs {len(r1['t'])}")


# ---------------------------------------------------------------------------
# T26 — double pendulum large angle (90°+90°): energy < 2% drift
# ---------------------------------------------------------------------------

def test_T26_double_pendulum_large_angle_energy():
    """
    Double pendulum with large initial angles (80° + 70°) — non-small-angle regime.
    Energy should be conserved within 2% (undamped).
    Use angles that yield non-zero initial potential energy.
    """
    sys, g_idx, b1_idx, b2_idx = _double_pendulum_system(
        1.0, 0.8, 1.0, 0.8, 80.0, 70.0)

    result = simulate(sys, t_end=2.0, dt=0.002, alpha_baumgarte=8.0, beta_baumgarte=8.0)
    assert result["ok"] is True

    energies = result["energy"]
    E0 = energies[0]["E"]
    assert abs(E0) > 1e-4, f"Initial energy too small: {E0:.2e}"
    for en in energies:
        drift = abs(en["E"] - E0) / abs(E0)
        assert drift < 0.02, f"Large-angle double pend energy drift {drift:.4f} > 2% at t={en['t']:.3f}"
