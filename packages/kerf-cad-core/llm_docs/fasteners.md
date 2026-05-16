# Bolted Joint Analysis (VDI 2230 / Shigley)

Pure-Python bolted-joint calculation tools. No OCC dependency. All tools are
stateless — they compute and return results; no DB write. Units: SI (N, m, Pa).

---

## When to use

Use these tools when the user asks about bolts, screws, fasteners, threaded
joints, preload, tightening torque, clamping force, joint separation, thread
stripping, slip resistance, or bolt fatigue.

Keywords: bolt, screw, fastener, preload, torque, clamp, joint, thread, nut,
VDI 2230, Shigley, engagement, slip, separation, fatigue endurance.

---

## Tools

### `bolt_preload_from_torque`

Compute clamp preload force from tightening torque: T = K·F·d → F = T/(K·d).

**Input:**
- `T` (required) — tightening torque (N·m)
- `d` (required) — nominal bolt diameter (m)
- `K` — nut factor (default 0.20 dry steel; range 0.10–0.35)

**Returns:** `F_preload_N`

---

### `bolt_stiffness`

Compute bolt axial stiffness treating bolt as shank + threaded segment in series.

**Input:**
- `d_shank` (required) — unthreaded shank diameter (m)
- `length_shank` (required) — shank length within grip (m; 0 for fully-threaded)
- `d_thread_minor` (required) — minor/stress-area diameter of thread (m)
- `length_thread` (required) — threaded section length within grip (m)
- `E_bolt` — Young's modulus (Pa; default 200e9)

**Returns:** `k_bolt_N_per_m`

---

### `clamped_member_stiffness`

Clamped-member axial stiffness via conical-frustum model (VDI 2230 Annex A).

**Input:**
- `grip_length` (required) — total clamped grip (m)
- `E_clamp` (required) — effective Young's modulus of clamped parts (Pa)
- `d_bolt` (required) — nominal bolt diameter (m)
- `half_angle_deg` — frustum half-angle α (default 30°)

**Returns:** `k_clamp_N_per_m`

---

### `bolt_joint_load_factor`

Compute joint load factor Φ = k_bolt / (k_bolt + k_clamp).

**Input:**
- `k_bolt` (required) — bolt axial stiffness (N/m)
- `k_clamp` (required) — clamped-member stiffness (N/m)

**Returns:** `Phi` (dimensionless, 0–1)

---

### `bolt_working_stress`

Combined tensile + torsional working stress in a bolt.

**Input:**
- `F_preload`, `F_external`, `Phi`, `A_stress` (all required)
- `Kb` — bending stress concentration factor (default 1.0)
- `torque_Nm` — residual wrench torque (N·m; default 0)
- `d_m` — mean pitch diameter (m; required if torque_Nm > 0)

**Returns:** `sigma_total_Pa`, `sigma_von_mises_Pa`

---

### `bolt_separation_safety`

Joint separation safety factor: n_sep = F_preload / [F_external·(1−Φ)].

**Input:** `F_preload`, `F_external`, `Phi` (all required)

**Returns:** `n_sep`, `separated` flag; warns if n_sep < 1.2

---

### `bolt_slip_safety`

Friction-grip slip safety: n_slip = μ·F_preload·n_bolts / F_shear.

**Input:**
- `F_preload`, `F_shear`, `mu` (all required)
- `n_bolts` — bolt count (default 1)

**Returns:** `n_slip`, `slips` flag; warns if n_slip < 1.25

---

### `bolt_fatigue_check`

Modified-Goodman fatigue check: Kf·σ_a/Se + σ_m/Sut ≤ 1.

**Input:** `sigma_a`, `Se`, `sigma_m`, `Sut` (all required); `Kf` (default 1.0)

**Returns:** `goodman_ratio`, `fatigue_ok`, `n_goodman`

---

### `bolt_strip_length`

Minimum thread engagement length to prevent stripping (Shigley §8-7 shear-area).

**Input:** `F_preload`, `F_external`, `Phi`, `d_nom`, `thread_pitch`, `Ssy_bolt`, `Ssy_nut` (all required); `safety_factor` (default 2.0)

**Returns:** `L_e_required_m`

---

## Example

```
1. bolt_preload_from_torque  T:50  d:0.016  K:0.20
   → F_preload_N: 15625

2. bolt_stiffness  d_shank:0.016  length_shank:0.020
                   d_thread_minor:0.01376  length_thread:0.010
   → k_bolt_N_per_m: ~285e6

3. clamped_member_stiffness  grip_length:0.030  E_clamp:200e9  d_bolt:0.016
   → k_clamp_N_per_m: ~1.2e9

4. bolt_joint_load_factor  k_bolt:285e6  k_clamp:1200e6
   → Phi: 0.19

5. bolt_separation_safety  F_preload:15625  F_external:8000  Phi:0.19
   → n_sep: 2.41  separated: false
```
