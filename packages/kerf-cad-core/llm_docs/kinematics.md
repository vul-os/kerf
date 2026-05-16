# Planar Kinematics — Four-Bar Linkages, Slider-Cranks, and Cam Followers

Pure-Python planar mechanism kinematics. No OCC dependency. All tools are
stateless — they compute and return results; no DB write. Units: consistent
length units (mm or m), degrees, rad/s.

References: Norton, "Design of Machinery", 5th ed.;
Shigley & Uicker, "Theory of Machines & Mechanisms", 4th ed.

---

## When to use

Trigger on: four-bar linkage, Grashof condition, crank-rocker, double-crank,
coupler curve, coupler point, slider-crank, piston mechanism, connecting rod,
cam follower, cycloidal cam, harmonic cam, follower lift, dwell, rise/fall,
mechanism analysis, linkage synthesis, transmission angle, kinematic analysis,
mechanism design.

---

## Tools

### `four_bar_grashof`

Classify a four-bar linkage by the Grashof condition.

**Key inputs:** `r1` (ground), `r2` (crank), `r3` (coupler), `r4` (output).

**Returns:** Grashof type (`crank-rocker`, `double-crank`, `rocker-crank`,
`double-rocker`, `non-Grashof`, or `change-point`), grashof flag, and link lengths.

---

### `four_bar_position`

Four-bar position analysis via the Freudenstein equation.

**Key inputs:** `r1`, `r2`, `r3`, `r4`, `theta2_deg` (crank angle), `branch`
(1=open, -1=crossed).

**Returns:** `theta3_deg` (coupler angle), `theta4_deg` (output angle), joint
coordinates, warnings for singular/locked configurations.

---

### `four_bar_transmission_angle`

Compute the transmission angle at a given crank position.

**Key inputs:** `r1`, `r2`, `r3`, `r4`, `theta2_deg`.

**Returns:** `mu_deg` (transmission angle) and acceptability flag.
Good design: 40° ≤ μ ≤ 140°.

---

### `four_bar_coupler_curve`

Trace the coupler-point path over one full crank revolution.

**Key inputs:** `r1`, `r2`, `r3`, `r4`, `px` (coupler point x-offset),
`py` (coupler point y-offset), `n_points` (default 72), `branch`.

**Returns:** list of `{theta2_deg, x, y}` — the coupler-point trajectory.

---

### `slider_crank`

Slider-crank position, velocity, and acceleration analysis.

**Key inputs:** `r` (crank radius), `l` (connecting-rod length), `theta_deg`
(crank angle), `omega_rad_s`, `alpha_rad_s2`.

**Returns:** `x_B` (slider position), `v_B` (velocity), `a_B` (acceleration),
phi_deg (connecting-rod angle), warnings for singular configurations.

---

### `cam_follower_cycloidal`

Cycloidal cam-follower displacement, velocity, and acceleration.

**Key inputs:** `h` (total lift), `beta_deg` (cam angle for segment),
`theta_deg` (current cam angle within segment), `rise` (True=rise, False=fall).

**Returns:** `displacement`, `velocity_per_omega`, `acceleration_per_omega2`.
Best for high-speed cams — zero acceleration at both ends of segment.

---

### `cam_follower_harmonic`

Harmonic (cosine/SHM) cam-follower displacement, velocity, and acceleration.

**Key inputs:** `h`, `beta_deg`, `theta_deg`, `rise`.

**Returns:** `displacement`, `velocity_per_omega`, `acceleration_per_omega2`.
Warning always included about acceleration discontinuity at segment boundaries.

---

## Example

**User:** "Check if my four-bar linkage r1=100, r2=40, r3=120, r4=80 mm is
Grashof and find the output angle when the crank is at 45°."

**Tools:**
1. `four_bar_grashof` r1:100 r2:40 r3:120 r4:80 → classify linkage type.
2. `four_bar_position` r1:100 r2:40 r3:120 r4:80 theta2_deg:45 → theta4_deg.
