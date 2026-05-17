# Multibody Dynamics (mbd)

Planar (2-D) constrained rigid-body dynamics solver with Baumgarte
constraint stabilisation; supports pendulums, slider-cranks, and
general custom mechanisms.

---

## When to use

Reach for these tools when the user asks about:

- simulating a single or double pendulum trajectory over time
- spring-mass oscillator (SHM, damped response)
- slider-crank mechanism kinematics/dynamics
- general planar linkage with revolute, prismatic, fixed, or distance joints
- extracting joint reaction forces or energy history from a mechanism
- verifying analytical period/frequency against numerical integration

---

## Tools

### `mbd_simulate_pendulum`

Simulate a simple or double pendulum.  Returns time-domain body
trajectories, angles, angular velocities, energy history, and the
analytical small-angle period T = 2π·√(L/g) for comparison.

**Required:** `L1` (m), `m1` (kg)
**Optional:** `theta1_deg` (default 10°), `L2`, `m2`, `theta2_deg`, `t_end` (default 5 s), `dt` (default 0.005 s), `g` (default 9.80665)
**Returns:** `{ok, t, q, qd, energy, bob1_theta_rad, T_analytical_small_angle_s, double, n_steps}`

---

### `mbd_simulate_spring_mass`

Simulate a 1-D spring-mass oscillator.  Prismatic joint constrains the
mass to the x-axis; a `SpringDamper` element applies the restoring force.
Returns trajectory, energy, and analytical ω = √(k/m).

**Required:** `mass` (kg), `k` (N/m)
**Optional:** `x0` (default 0.1 m), `c` (damping, default 0), `t_end`, `dt`
**Returns:** `{ok, t, x_trajectory, omega_analytical_rad_s, T_analytical_s, energy, n_steps}`

---

### `mbd_simulate_slider_crank_mbd`

Simulate a slider-crank mechanism.  Crank of radius r rotates about
the origin; connecting rod of length l links crank pin to a prismatic
slider.  Returns slider position compared to the kinematic closed-form
x_B = r·cos(θ) + √(l² − r²·sin²(θ)).

**Required:** `r` (m), `l` (m, must be > r)
**Optional:** `m_crank` (default 1 kg), `m_rod` (0.5 kg), `m_slider` (1 kg), `omega0` (10 rad/s), `t_end` (0.5 s), `dt` (0.001 s)
**Returns:** `{ok, slider_x_mbd, slider_x_kinematic, crank_theta_rad, t, energy, reactions}`

---

### Programmatic API (`kerf_cad_core.mbd.solver`)

All tools are thin wrappers around the `MBDSystem` / `simulate` API:

```python
from kerf_cad_core.mbd.solver import (
    MBDSystem, Body, RevoluteJoint, PrismaticJoint,
    FixedJoint, DistanceJoint, SpringDamper,
    GravityForce, AppliedForce, AppliedTorque,
    simulate,
)

sys = MBDSystem()
g   = sys.add_body(Body(mass=1.0, inertia=1.0, fixed=True))
b1  = sys.add_body(Body(mass=1.0, inertia=0.01, x0=0.0, y0=-1.0))
sys.add_joint(RevoluteJoint(g, b1, s_i=(0,0), s_j=(0, 1.0)))
sys.add_force(GravityForce())
result = simulate(sys, t_end=5.0, dt=0.001)
# result["ok"] True; result["q"] list of [x,y,theta,...] at each step
```

Integrator: semi-implicit trapezoidal (Newmark-like) with Baumgarte
stabilisation (default α = β = 5).  Coordinate projection Newton
iterations (3 max) enforce constraint satisfaction after each step.

---

## Supported input contract

- Planar (2-D) systems only; 3-D MBD is not supported.
- No closed-form stiff-ODE solver; step size must be small enough for
  stability (dt ≈ 0.001–0.005 s for typical mechanisms).
- Constraint Jacobian is computed via finite differences (h = 1e-7).
- Fixed bodies are kinematic grounds; their DOF are pinned via constraint rows.
- Pure Python — no numpy/scipy dependency.

---

## Usage examples

**Simple pendulum (10° release, 1 m, 1 kg):**

```
mbd_simulate_pendulum
  L1: 1.0  m1: 1.0  theta1_deg: 10  t_end: 10  dt: 0.005
→ {T_analytical_small_angle_s: 2.006, bob1_theta_rad: [...]}
```

**Damped spring-mass (k = 100 N/m, m = 0.5 kg, c = 2 N·s/m):**

```
mbd_simulate_spring_mass
  mass: 0.5  k: 100  x0: 0.05  c: 2.0  t_end: 3.0
→ {omega_analytical_rad_s: 14.14, T_analytical_s: 0.444}
```

**Slider-crank (r=0.1 m, l=0.3 m, ω₀=10 rad/s):**

```
mbd_simulate_slider_crank_mbd
  r: 0.1  l: 0.3  omega0: 10.0  t_end: 0.5  dt: 0.001
→ {slider_x_mbd: [...], slider_x_kinematic: [...]}
```

---

## References

Shabana, A.A. — *Computational Dynamics*, 3rd ed. Wiley, 2010 (Chapter 4: augmented Lagrangian MBD formulation).
Haug, E.J. — *Computer-Aided Kinematics and Dynamics of Mechanical Systems*, Vol. 1. Allyn & Bacon, 1989.
