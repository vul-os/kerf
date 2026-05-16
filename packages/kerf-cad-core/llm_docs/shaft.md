# Shaft and Bearing Sizing

Pure-Python shaft design and bearing selection per ASME B106.1M, ISO 281, and
ANSI B17.1. Computes minimum shaft diameter from bending and torsion loads,
first lateral critical speed, bearing L10 rating life, and standard key
cross-section with stress checks. No OCC dependency.

---

## When to use

Reach for this module when the user asks about:

- sizing a shaft for combined bending and torsion (Goodman fatigue or Tresca)
- finding the minimum shaft diameter for a given torque and bending moment
- checking whether a shaft will resonate (critical whirl speed)
- calculating bearing rating life (L10 life in hours or millions of revolutions)
- selecting a standard key cross-section for a shaft-hub connection
- checking shear and compressive stress on a key
- power transmission shaft design: motor shafts, gearbox shafts, drive shafts
- comparing ball vs roller bearing life for a given load and speed

---

## Tools

### `shaft_diameter`

Compute the required minimum solid circular shaft diameter from combined bending
moment M and torque T. Two criteria: `DE-Goodman` (Distortion-Energy + Goodman
fatigue, default — use endurance limit Se as `sigma_allow`) or `max-shear` (Tresca
static). Accepts fatigue stress concentration factors `Kf` (bending) and `Kfs`
(torsion) and an additional `safety_factor`. Returns `diameter_m` in metres.

### `shaft_critical_speed`

Compute the first lateral whirl critical speed of a uniform shaft using the
Euler-Bernoulli beam equation. Boundary conditions: `simply-supported` (default)
or `fixed-fixed`. Inputs: shaft length (m), mass per unit length (kg/m), Young's
modulus E (Pa), second moment of area I (m⁴). Returns `omega_rad_s` and `n_rpm`.
Operating speed should remain ≤ 75% of `n_rpm`.

### `bearing_l10`

Compute ISO 281 basic L10 rating life for a rolling bearing. Inputs: basic dynamic
load rating C (N), equivalent dynamic load P (N), and rotational speed n_rpm.
Exponent: ball bearings p=3, roller bearings p=10/3. Returns `L10_rev` (10⁶
revolutions) and `L10_hours` at the given speed.

### `key_size`

Select the standard ANSI B17.1 / DIN 6885 key cross-section (width × height) for
a given shaft diameter (6–230 mm range), then check shear stress (τ = F / (w·L))
and bearing/compressive stress (σ_c = F / (h/2·L)) for the transmitted torque.
Returns key dimensions, computed stresses, allowables, pass/fail flags, and safety
factors. Material options: `steel_1045`, `steel_1020`, `stainless_304`,
`cast_iron`.

---

## Example

**User ask:** "I have a shaft with 250 N·m bending and 400 N·m torque, endurance
limit 200 MPa. What diameter do I need, and will a 50 mm shaft resonate below
3000 rpm?"

```
1. shaft_diameter
     M:250  T:400  sigma_allow:200e6  method:"DE-Goodman"
   → {diameter_m:0.0412, …}

2. shaft_critical_speed
     length_m:0.8  mass_per_m:15.6  E:200e9
     I:3.14e-7   supports:"simply-supported"
   → {n_rpm:4820, omega_rad_s:505, …}
   (4820 rpm > 3000 rpm operating speed → safe)

3. key_size
     shaft_d_mm:50  torque_Nm:400  material:"steel_1045"
   → {width_mm:14, height_mm:9, shear_ok:true, bearing_ok:true, …}
```

---

## Notes

- All tools are **pure-Python**; no OCC dependency.
- `shaft_diameter` uses metres (SI) throughout; convert mm inputs as needed.
- `bearing_l10` assumes basic rating — no life adjustment factors (a1, aISO).
- `key_size` key length defaults to 1.5 × shaft_d_mm if not provided.
- Invalid inputs return `{ok:false, reason:...}` — never raise.
- References: ASME B106.1M-1985, ISO 281:2007, ANSI B17.1-1967.
