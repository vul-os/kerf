# Mechanical Vibration Analysis

Pure-Python vibration analysis tools (SDOF, 2-DOF, beams, shafts, isolators).
No OCC dependency. Units: SI (kg, N/m, rad/s, m).

---

## When to use

Use these tools when the user asks about natural frequency, resonance, damping,
vibration isolation, forced response, whirl speed, critical speed, mode shapes,
rotating unbalance, or vibration transmissibility.

Keywords: natural frequency, resonance, damping, SDOF, vibration, isolation,
transmissibility, log decrement, magnification factor, rotating unbalance,
critical speed, shaft whirl, beam natural frequency, 2-DOF, eigenvalue,
mode shape.

---

## Tools

### `vibration_sdof_natural_frequency`

Undamped natural frequency of a SDOF spring-mass system: ωn = √(k/m).

**Input:** `m` (kg, required), `k` (N/m, required)

**Returns:** `omega_n_rad_s`, `fn_Hz`

---

### `vibration_sdof_damped_frequency`

Damped natural frequency and damping ratio. c_cr = 2√(km), ζ = c/c_cr, ωd = ωn√(1−ζ²).

**Input:** `m`, `k`, `c` (N·s/m) — all required

**Returns:** `omega_d_rad_s`, `zeta`, `c_cr`, `regime` (underdamped/critically_damped/overdamped)

---

### `vibration_sdof_log_decrement`

Estimate damping ratio from measured free-vibration peak amplitudes.
δ = (1/n)·ln(x1/xn),  ζ = δ/√(4π² + δ²).

**Input:** `x1` (first peak amplitude), `xn` (n-th peak amplitude), `n` (cycle count) — all required

**Returns:** `delta`, `zeta`, `zeta_approx`

---

### `vibration_sdof_free_response`

Free-vibration displacement x(t) at time t for given initial conditions.
Handles underdamped, critically damped, and overdamped cases.

**Input:** `m`, `k`, `c`, `x0` (initial displacement m), `v0` (initial velocity m/s), `t` (s) — all required

**Returns:** `x_t` (m), `zeta`, `omega_n`, `regime`

---

### `vibration_sdof_harmonic`

Dynamic magnification factor M and phase angle φ for harmonic forcing.
M = 1/√[(1−r²)²+(2ζr)²],  φ = arctan[2ζr/(1−r²)].  Warns near resonance.

**Input:** `zeta`, `r` (frequency ratio ω/ωn) — both required

**Returns:** `M`, `phi_deg`, `r`, resonance warning if r ≈ 1

---

### `vibration_sdof_transmissibility`

Base-excitation transmissibility TR. TR < 1 (isolation) requires r > √2.

**Input:** `zeta`, `r` — both required

**Returns:** `TR`, isolation flag, warning if not in isolation zone

---

### `vibration_sdof_rotating_unbalance`

Steady-state amplitude for rotating-unbalance excitation.
X = (m_u·e/m) · r²/√[(1−r²)²+(2ζr)²].

**Input:** `m`, `k`, `c`, `m_u` (unbalance mass kg), `e` (eccentricity m), `omega` (rad/s) — all required

**Returns:** `X_m` (amplitude), non-dimensional ratio `MX_over_mue`

---

### `vibration_2dof_eigen`

Natural frequencies and mode shapes of an undamped 2-DOF spring-mass system
(closed-form 2×2 solution).

**Input:** `m1`, `m2`, `k1`, `k2` (required); `k3` (spring to ground from m2, default 0)

**Returns:** `omega1`, `omega2` (rad/s), `fn1`, `fn2` (Hz), mode shapes `[1, u2_mode1]`, `[1, u2_mode2]`

---

### `vibration_beam_frequency`

Euler-Bernoulli beam natural frequency: ωn = (βL)² · √(EI/(μL⁴)).

**Input:** `mode`, `length_m`, `mass_per_m` (kg/m), `E` (Pa), `I` (m⁴) — all required; `bc` enum `'simply-supported'`/`'cantilever'` (default simply-supported)

**Returns:** `omega_n_rad_s`, `fn_Hz`, `betaL`

---

### `vibration_shaft_whirl_rayleigh`

First lateral whirl (critical) speed of a multi-disk shaft by Rayleigh's method.

**Input:** `lengths_m` (disk positions from left bearing), `masses_kg`, `E`, `I` — all required; `span_m` (optional)

**Returns:** `omega_cr_rad_s`, `n_cr_rpm`, static deflections at each disk

---

### `vibration_isolator_stiffness`

Required undamped isolator stiffness to achieve target transmissibility TR.

**Input:** `m` (isolated mass kg), `omega_exc` (excitation rad/s), `TR_target` (0 < TR < 1) — all required

**Returns:** `k_N_per_m`, `omega_n_rad_s`, `r`, `static_deflection_m`

---

## Example

```
1. vibration_sdof_natural_frequency  m:50  k:200000
   → omega_n: 63.25 rad/s  fn: 10.07 Hz

2. vibration_sdof_transmissibility  zeta:0.05  r:2.5
   → TR: 0.197  isolated: true

3. vibration_isolator_stiffness  m:100  omega_exc:314.16  TR_target:0.05
   → k: 217 kN/m  omega_n: 46.7 rad/s
```
